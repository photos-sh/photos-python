"""Describes each API call once, for the sync and the async client alike.

A function here turns the caller's arguments into a :class:`Request`: what to
send and how to read the answer. The clients only send it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar, Union, cast
from urllib.parse import quote, urlencode

import httpx

from ._results import (
    BlurFacesResult,
    CropResult,
    FixResult,
    IdPhotoResult,
    ImageResult,
    JobItemResult,
    RemoveBackgroundResult,
    RemoveTextResult,
    RestoreFacesResult,
    SelectResult,
    VectorizeResult,
    parse_blur_faces,
    parse_crop,
    parse_fix,
    parse_id_photo,
    parse_image,
    parse_job_item,
    parse_remove_background,
    parse_remove_text,
    parse_restore_faces,
    parse_select,
    parse_vectorize,
)
from ._types import (
    Account,
    BarcodesResult,
    CaptionResult,
    CheckResult,
    FacesResult,
    HealthStatus,
    IdentifyResult,
    IdPhotoDocument,
    ImageInput,
    Job,
    JobParams,
    JobSummary,
    LabelResult,
    MarketplaceProfile,
    PaletteResult,
    Point,
    Preset,
    Rect,
    TextResult,
    WebhookSecret,
)

T = TypeVar("T")

#: A multipart file part as httpx takes it: ``(field, (file name, content))``.
FilePart = tuple[str, tuple[str, bytes]]

MAX_IMAGES = 8


@dataclass(frozen=True)
class Request(Generic[T]):
    """One API call: what to send, and how to turn the response into ``T``."""

    method: str
    path: str
    parse: Callable[[httpx.Response], T]
    params: list[tuple[str, str]] = field(default_factory=list)
    files: Optional[list[FilePart]] = None
    data: Optional[dict[str, Union[str, list[str]]]] = None
    json: Optional[Any] = None
    #: Whether a connection failure may be retried (not for creating a job:
    #: the request may have arrived).
    retry_connection_errors: bool = True
    #: Whether 503 is retried and raised as an error (not for ``health``).
    unavailable_is_error: bool = True


# --- encoding -------------------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def query(options: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Query pairs for the options that were set. Sequences repeat the name."""
    pairs: list[tuple[str, str]] = []
    for name, value in options.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((name, _text(v)) for v in value)
        else:
            pairs.append((name, _text(value)))
    return pairs


def _is_single_image(value: object) -> bool:
    return isinstance(value, (str, os.PathLike, bytes, bytearray, memoryview)) or hasattr(
        value, "read"
    )


def read_image(image: ImageInput, default_name: str = "image") -> tuple[str, bytes]:
    """The file name and bytes of an image argument."""
    if isinstance(image, (bytes, bytearray, memoryview)):
        return default_name, bytes(image)
    if isinstance(image, (str, os.PathLike)):
        path = os.fspath(image)
        with open(path, "rb") as f:
            return os.path.basename(path) or default_name, f.read()
    if hasattr(image, "read"):
        content = image.read()
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("the image file object must be opened in binary mode")
        name = getattr(image, "name", None)
        file_name = os.path.basename(name) if isinstance(name, str) else ""
        return file_name or default_name, bytes(content)
    raise TypeError(
        "an image must be a path (str or os.PathLike), bytes or a binary file object, "
        f"not {type(image).__name__}"
    )


def _image_parts(images: Iterable[ImageInput]) -> list[FilePart]:
    return [("image", read_image(image)) for image in images]


def _recipe_parts(recipe: Optional[str]) -> list[FilePart]:
    """A recipe goes as a file part: every endpoint that takes one accepts it this way."""
    return [] if recipe is None else [("recipe", ("recipe.toml", recipe.encode()))]


def _several(images: Union[ImageInput, Sequence[ImageInput]]) -> list[ImageInput]:
    """One image or a sequence of them, as a list of 1 to 8."""
    if _is_single_image(images):
        return [cast(ImageInput, images)]
    listed = list(cast("Sequence[ImageInput]", images))
    if not 1 <= len(listed) <= MAX_IMAGES:
        raise ValueError(f"send 1 to {MAX_IMAGES} images, not {len(listed)}")
    return listed


def _rects(rect: Union[Rect, Sequence[Rect], None]) -> list[str]:
    if rect is None:
        return []
    if isinstance(rect, str):
        return [rect]
    items: Sequence[Any] = rect
    if len(items) == 4 and all(isinstance(v, int) for v in items):
        items = [rect]
    encoded = []
    for item in items:
        if isinstance(item, str):
            encoded.append(item)
        elif len(item) == 4:
            encoded.append(",".join(str(int(v)) for v in item))
        else:
            raise ValueError(f"a rect is (x, y, width, height), not {item!r}")
    return encoded


def _points(point: Union[Point, Sequence[Point], None]) -> list[str]:
    if point is None:
        return []
    if isinstance(point, str):
        return [point]
    items: Sequence[Any] = point
    if len(items) == 2 and all(isinstance(v, (int, float)) for v in items):
        items = [point]
    encoded = []
    for item in items:
        if isinstance(item, str):
            encoded.append(item)
        elif len(item) == 2:
            encoded.append(",".join(str(v) for v in item))
        else:
            raise ValueError(f"a point is (x, y), not {item!r}")
    return encoded


def _json(response: httpx.Response) -> Any:
    return response.json()


def _job_path(job_id: str) -> str:
    return "/v1/jobs/" + quote(job_id, safe="")


# --- image endpoints ------------------------------------------------------------------


def _image_request(
    path: str,
    image: ImageInput,
    parse: Callable[[httpx.Response], T],
    options: Mapping[str, Any],
    **more: Optional[ImageInput],
) -> Request[T]:
    """``more`` are further images, by part name; the ones not given are left out."""
    files = _image_parts([image])
    for name, extra in more.items():
        if extra is not None:
            files.append((name, read_image(extra, name)))
    return Request("POST", path, parse, params=query(options), files=files)


def remove_background(
    image: ImageInput, *, background_image: Optional[ImageInput], **options: Any
) -> Request[RemoveBackgroundResult]:
    return _image_request(
        "/v1/remove-background",
        image,
        parse_remove_background,
        options,
        background=background_image,
    )


def resize(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/resize", image, parse_image, options)


def upscale(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/upscale", image, parse_image, options)


def erase(
    image: ImageInput,
    *,
    rect: Union[Rect, Sequence[Rect], None],
    mask: Optional[ImageInput],
    **options: Any,
) -> Request[ImageResult]:
    rects = _rects(rect)
    if not rects and mask is None:
        raise ValueError("erase needs the area to remove: give rect and/or mask")
    return _image_request("/v1/erase", image, parse_image, {"rect": rects, **options}, mask=mask)


def remove_text(image: ImageInput, **options: Any) -> Request[RemoveTextResult]:
    return _image_request("/v1/remove-text", image, parse_remove_text, options)


def run(image: ImageInput, *, preset: Optional[str], recipe: Optional[str]) -> Request[ImageResult]:
    if (preset is None) == (recipe is None):
        raise ValueError("run needs either a preset name or a recipe, not both")
    return Request(
        "POST",
        "/v1/run",
        parse_image,
        params=query({"preset": preset}),
        files=[*_image_parts([image]), *_recipe_parts(recipe)],
    )


def enhance(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/enhance", image, parse_image, options)


def crop(image: ImageInput, **options: Any) -> Request[CropResult]:
    return _image_request("/v1/crop", image, parse_crop, options)


def watermark(
    image: ImageInput, *, text: Optional[str], watermark: Optional[ImageInput], **options: Any
) -> Request[ImageResult]:
    if (text is None) == (watermark is None):
        raise ValueError("watermark needs either text or a watermark image, not both")
    return _image_request(
        "/v1/watermark", image, parse_image, {"text": text, **options}, watermark=watermark
    )


def expand(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/expand", image, parse_image, options)


def vectorize(image: ImageInput, **options: Any) -> Request[VectorizeResult]:
    return _image_request("/v1/vectorize", image, parse_vectorize, options)


def blur_faces(image: ImageInput, **options: Any) -> Request[BlurFacesResult]:
    return _image_request("/v1/blur-faces", image, parse_blur_faces, options)


def id_photo(image: ImageInput, **options: Any) -> Request[IdPhotoResult]:
    return _image_request("/v1/id-photo", image, parse_id_photo, options)


def denoise(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/denoise", image, parse_image, options)


def colorize(image: ImageInput, **options: Any) -> Request[ImageResult]:
    return _image_request("/v1/colorize", image, parse_image, options)


def select(
    image: ImageInput,
    *,
    point: Union[Point, Sequence[Point], None],
    exclude: Union[Point, Sequence[Point], None],
    box: Optional[Rect],
    **options: Any,
) -> Request[SelectResult]:
    points = _points(point)
    boxes = _rects(box)
    if not points and not boxes:
        raise ValueError("select needs the object: give point and/or box")
    if len(boxes) > 1:
        raise ValueError("select takes one box at most")
    params = {"point": points, "exclude": _points(exclude), "box": boxes, **options}
    return _image_request("/v1/select", image, parse_select, params)


def restore_faces(image: ImageInput, **options: Any) -> Request[RestoreFacesResult]:
    return _image_request("/v1/restore-faces", image, parse_restore_faces, options)


def fix(image: ImageInput, marketplace: str) -> Request[FixResult]:
    return _image_request("/v1/fix", image, parse_fix, {"marketplace": marketplace})


def check(image: ImageInput, **options: Any) -> Request[CheckResult]:
    return _image_request("/v1/check", image, _json, options)


def read_barcodes(image: ImageInput, **options: Any) -> Request[BarcodesResult]:
    return _image_request("/v1/barcodes", image, _json, options)


def read_text(image: ImageInput) -> Request[TextResult]:
    return _image_request("/v1/ocr", image, _json, {})


def read_label(images: Union[ImageInput, Sequence[ImageInput]]) -> Request[LabelResult]:
    return Request("POST", "/v1/label", _json, files=_image_parts(_several(images)))


def identify(
    images: Union[ImageInput, Sequence[ImageInput]], **options: Any
) -> Request[IdentifyResult]:
    return Request(
        "POST",
        "/v1/identify",
        _json,
        params=query(options),
        files=_image_parts(_several(images)),
    )


def palette(image: ImageInput, **options: Any) -> Request[PaletteResult]:
    return _image_request("/v1/palette", image, _json, options)


def find_faces(image: ImageInput, **options: Any) -> Request[FacesResult]:
    return _image_request("/v1/faces", image, _json, options)


def caption(image: ImageInput, **options: Any) -> Request[CaptionResult]:
    return _image_request("/v1/caption", image, _json, options)


# --- account and service --------------------------------------------------------------


def account() -> Request[Account]:
    return Request("GET", "/v1/account", _json)


def presets() -> Request[list[Preset]]:
    return Request("GET", "/v1/presets", _json)


def preset(name: str) -> Request[str]:
    return Request("GET", "/v1/presets/" + quote(name, safe=""), lambda response: response.text)


def marketplaces() -> Request[list[MarketplaceProfile]]:
    return Request("GET", "/v1/marketplaces", _json)


def id_photos() -> Request[list[IdPhotoDocument]]:
    return Request("GET", "/v1/id-photos", _json)


def webhook_secret() -> Request[WebhookSecret]:
    return Request("GET", "/v1/webhook-secret", _json)


def _health_status(response: httpx.Response) -> HealthStatus:
    status = response.json()["status"]
    if status not in ("ok", "loading", "failed"):
        raise ValueError(f"unexpected health status {status!r}")
    return cast(HealthStatus, status)


def health() -> Request[HealthStatus]:
    return Request("GET", "/health", _health_status, unavailable_is_error=False)


# --- jobs -----------------------------------------------------------------------------


def _json_params(params: Mapping[str, Any]) -> Union[dict[str, Any], str]:
    """A job's options for a JSON body: an object, or a query string when an
    option repeats (``point`` and ``exclude`` of ``select``), which the API
    does not read from an object."""
    if any(isinstance(value, (list, tuple)) for value in params.values()):
        return urlencode(query(params))
    return {name: value for name, value in params.items() if value is not None}


def create_job(
    operation: str,
    *,
    urls: Optional[Sequence[str]],
    images: Optional[Sequence[ImageInput]],
    params: Optional[JobParams],
    recipe: Optional[str],
    webhook_url: Optional[str],
) -> Request[Job]:
    if isinstance(urls, str):
        raise TypeError("urls must be a sequence of URLs, not one string")
    if images is not None and _is_single_image(images):
        raise TypeError("images must be a sequence of images, not one image")
    urls = list(urls or [])
    images = list(images or [])
    if not urls and not images:
        raise ValueError("a job needs at least one URL or image")

    if not images:
        body: dict[str, Any] = {"operation": operation, "inputs": urls}
        if params is not None:
            body["params"] = params if isinstance(params, str) else _json_params(params)
        if recipe is not None:
            body["recipe"] = recipe
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        return Request("POST", "/v1/jobs", _json, json=body, retry_connection_errors=False)

    data: dict[str, Union[str, list[str]]] = {"operation": operation}
    if params is not None:
        encoded = params.lstrip("?") if isinstance(params, str) else urlencode(query(params))
        if encoded:
            data["params"] = encoded
    if webhook_url is not None:
        data["webhook_url"] = webhook_url
    if urls:
        data["url"] = urls
    files = _recipe_parts(recipe) + [
        ("image", read_image(image, f"image-{n}")) for n, image in enumerate(images, start=1)
    ]
    return Request("POST", "/v1/jobs", _json, files=files, data=data, retry_connection_errors=False)


def get_job(job_id: str) -> Request[Job]:
    return Request("GET", _job_path(job_id), _json)


def list_jobs() -> Request[list[JobSummary]]:
    return Request("GET", "/v1/jobs", _json)


def delete_job(job_id: str) -> Request[None]:
    return Request("DELETE", _job_path(job_id), lambda response: None)


def job_item(job_id: str, n: int) -> Request[JobItemResult]:
    return Request("GET", f"{_job_path(job_id)}/items/{int(n)}", parse_job_item)
