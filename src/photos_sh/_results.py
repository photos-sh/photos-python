"""Results that carry an image (or, for job items, whatever the item produced)."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import httpx

from ._errors import PhotosError


@dataclass(frozen=True)
class ImageResult:
    """An image the API returned.

    ``width``, ``height`` and ``quality`` come from the ``X-Image-*`` headers;
    ``quality`` is only present for lossy formats. ``server_timing`` is the raw
    ``Server-Timing`` header (per-step durations).
    """

    content: bytes = field(repr=False)
    content_type: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    quality: Optional[int] = None
    server_timing: Optional[str] = None

    def save(self, path: Union[str, os.PathLike[str]]) -> None:
        """Write the bytes to ``path``."""
        with open(path, "wb") as f:
            f.write(self.content)


@dataclass(frozen=True)
class RemoveTextResult(ImageResult):
    """The image with text removed, and how many text lines went and stayed."""

    removed: int = 0
    kept: int = 0


@dataclass(frozen=True)
class FixResult(ImageResult):
    """The fixed image, whether it now passes, and the finding codes still present."""

    passed: bool = False
    findings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemoveBackgroundResult(ImageResult):
    """The cutout, or the staged image.

    ``subject_found`` is ``False`` when no subject was found (under 3% of the
    photo): the photo is then returned as it was. Otherwise the API does not
    say, and it is ``None``.
    """

    subject_found: Optional[bool] = None


@dataclass(frozen=True)
class CropResult(ImageResult):
    """The cropped image, and whether a subject was found.

    Without a subject the crop is centred. ``subject_found`` is ``None`` when
    the API did not say.
    """

    subject_found: Optional[bool] = None


@dataclass(frozen=True)
class VectorizeResult(ImageResult):
    """An SVG, and how many paths it has.

    ``content`` is the SVG's text as bytes; ``width`` and ``height`` are the
    size the image was traced at.
    """

    paths: int = 0


@dataclass(frozen=True)
class BlurFacesResult(ImageResult):
    """The photo with its faces hidden, and how many were found and hidden."""

    faces: int = 0


@dataclass(frozen=True)
class RestoreFacesResult(ImageResult):
    """The photo with its faces restored.

    ``faces`` were restored; ``faces_skipped`` were left alone because they
    are large and detailed enough.
    """

    faces: int = 0
    faces_skipped: int = 0


@dataclass(frozen=True)
class IdPhotoResult(ImageResult):
    """The framed identity photo, and what the tool could see is wrong with it.

    ``passed`` says that ``findings`` is empty; it is not an approval of the
    photo. ``head_mm`` is the head's height in the result, chin to crown.
    """

    passed: bool = False
    findings: list[str] = field(default_factory=list)
    head_mm: Optional[float] = None


@dataclass(frozen=True)
class SelectResult(ImageResult):
    """The object cut out (or its mask), and how well the model thinks it fits (0 to 1)."""

    score: Optional[float] = None


@dataclass(frozen=True)
class JobItemResult(ImageResult):
    """The result of one job item: an image or JSON, depending on the operation.

    The image fields are filled when it is an image; ``json()`` decodes a JSON
    result. ``headers`` holds every response header (case-insensitive).

    The methods named after an operation (:meth:`fix`, :meth:`crop`, ...) give
    the same typed result as the client's method. Each raises
    :class:`~photos_sh.PhotosError` when the item lacks that operation's
    header: the job ran another operation, or the server is too old to keep
    the header on job items. Only :meth:`remove_background` cannot tell, and
    does not raise.
    """

    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_json(self) -> bool:
        return self.content_type.startswith("application/json")

    def json(self) -> Any:
        """The decoded JSON body (for ``ocr``, ``barcodes``, ``check``, ``label``,
        ``palette``, ``faces`` and ``caption`` jobs)."""
        return json.loads(self.content)

    def _headers_of(self, operation: str, name: str) -> dict[str, str]:
        """The headers, names in lower case; an error unless ``name`` is among them."""
        headers = _lower(self.headers)
        if name not in headers:
            raise PhotosError(
                f"this job item has no {name} header: it is not the result of a {operation} "
                "job, or the server does not keep that header on job items"
            )
        return headers

    def remove_text(self) -> RemoveTextResult:
        """This item as the result of ``remove_text``, with ``removed`` and ``kept``.

        Raises :class:`~photos_sh.PhotosError` when the result has no
        ``X-Text-Removed`` header: the job ran another operation, or the
        server is too old to keep it on job items.
        """
        return _remove_text(self.content, self._headers_of("remove-text", "x-text-removed"))

    def fix(self) -> FixResult:
        """This item as the result of ``fix``, with ``passed`` and ``findings``.

        Raises :class:`~photos_sh.PhotosError` when the result has no
        ``X-Marketplace-Passed`` header: the job ran another operation, or the
        server is too old to keep it on job items.
        """
        return _fix(self.content, self._headers_of("fix", "x-marketplace-passed"))

    def remove_background(self) -> RemoveBackgroundResult:
        """This item as the result of ``remove_background``, with ``subject_found``.

        It does not raise: the API sends ``X-Subject-Found`` when no subject
        was found (the photo is then returned as it was), so the header is
        absent from most results, and ``subject_found`` is then ``None``.
        """
        return _remove_background(self.content, _lower(self.headers))

    def crop(self) -> CropResult:
        """This item as the result of ``crop``, with ``subject_found``."""
        return _crop(self.content, self._headers_of("crop", "x-subject-found"))

    def vectorize(self) -> VectorizeResult:
        """This item as the result of ``vectorize``, with ``paths``."""
        return _vectorize(self.content, self._headers_of("vectorize", "x-paths"))

    def blur_faces(self) -> BlurFacesResult:
        """This item as the result of ``blur_faces``, with ``faces``."""
        return _blur_faces(self.content, self._headers_of("blur-faces", "x-faces"))

    def restore_faces(self) -> RestoreFacesResult:
        """This item as the result of ``restore_faces``, with ``faces`` and ``faces_skipped``."""
        return _restore_faces(self.content, self._headers_of("restore-faces", "x-faces-skipped"))

    def id_photo(self) -> IdPhotoResult:
        """This item as the result of ``id_photo``: ``passed``, ``findings``, ``head_mm``."""
        return _id_photo(self.content, self._headers_of("id-photo", "x-id-photo-passed"))

    def select(self) -> SelectResult:
        """This item as the result of ``select``, with ``score``."""
        return _select(self.content, self._headers_of("select", "x-select-score"))


# --- reading headers ------------------------------------------------------------------
# The functions below take header names in lower case, as `_lower` gives them.


def _lower(headers: Mapping[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def _int(headers: Mapping[str, str], name: str) -> Optional[int]:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _float(headers: Mapping[str, str], name: str) -> Optional[float]:
    try:
        number = float(headers[name])
    except (KeyError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(headers: Mapping[str, str], name: str) -> Optional[bool]:
    """``true`` or ``false``; None when the header is absent or says neither."""
    value = headers.get(name, "").strip().lower()
    return {"true": True, "false": False}.get(value)


def _codes(headers: Mapping[str, str], name: str) -> list[str]:
    """A comma-separated list of codes; an absent or empty header is no codes."""
    codes = [code.strip() for code in headers.get(name, "").split(",")]
    return [code for code in codes if code]


def _image_fields(content: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
    return {
        "content": content,
        "content_type": headers.get("content-type", ""),
        "width": _int(headers, "x-image-width"),
        "height": _int(headers, "x-image-height"),
        "quality": _int(headers, "x-image-quality"),
        "server_timing": headers.get("server-timing"),
    }


def _remove_text(content: bytes, headers: Mapping[str, str]) -> RemoveTextResult:
    return RemoveTextResult(
        **_image_fields(content, headers),
        removed=_int(headers, "x-text-removed") or 0,
        kept=_int(headers, "x-text-kept") or 0,
    )


def _fix(content: bytes, headers: Mapping[str, str]) -> FixResult:
    return FixResult(
        **_image_fields(content, headers),
        passed=_bool(headers, "x-marketplace-passed") is True,
        findings=_codes(headers, "x-marketplace-findings"),
    )


def _remove_background(content: bytes, headers: Mapping[str, str]) -> RemoveBackgroundResult:
    return RemoveBackgroundResult(
        **_image_fields(content, headers), subject_found=_bool(headers, "x-subject-found")
    )


def _crop(content: bytes, headers: Mapping[str, str]) -> CropResult:
    return CropResult(
        **_image_fields(content, headers), subject_found=_bool(headers, "x-subject-found")
    )


def _vectorize(content: bytes, headers: Mapping[str, str]) -> VectorizeResult:
    return VectorizeResult(**_image_fields(content, headers), paths=_int(headers, "x-paths") or 0)


def _blur_faces(content: bytes, headers: Mapping[str, str]) -> BlurFacesResult:
    return BlurFacesResult(**_image_fields(content, headers), faces=_int(headers, "x-faces") or 0)


def _restore_faces(content: bytes, headers: Mapping[str, str]) -> RestoreFacesResult:
    return RestoreFacesResult(
        **_image_fields(content, headers),
        faces=_int(headers, "x-faces") or 0,
        faces_skipped=_int(headers, "x-faces-skipped") or 0,
    )


def _id_photo(content: bytes, headers: Mapping[str, str]) -> IdPhotoResult:
    return IdPhotoResult(
        **_image_fields(content, headers),
        passed=_bool(headers, "x-id-photo-passed") is True,
        findings=_codes(headers, "x-id-photo-findings"),
        head_mm=_float(headers, "x-id-photo-head-mm"),
    )


def _select(content: bytes, headers: Mapping[str, str]) -> SelectResult:
    return SelectResult(**_image_fields(content, headers), score=_float(headers, "x-select-score"))


def parse_image(response: httpx.Response) -> ImageResult:
    return ImageResult(**_image_fields(response.content, _lower(response.headers)))


def parse_remove_text(response: httpx.Response) -> RemoveTextResult:
    return _remove_text(response.content, _lower(response.headers))


def parse_fix(response: httpx.Response) -> FixResult:
    return _fix(response.content, _lower(response.headers))


def parse_remove_background(response: httpx.Response) -> RemoveBackgroundResult:
    return _remove_background(response.content, _lower(response.headers))


def parse_crop(response: httpx.Response) -> CropResult:
    return _crop(response.content, _lower(response.headers))


def parse_vectorize(response: httpx.Response) -> VectorizeResult:
    return _vectorize(response.content, _lower(response.headers))


def parse_blur_faces(response: httpx.Response) -> BlurFacesResult:
    return _blur_faces(response.content, _lower(response.headers))


def parse_restore_faces(response: httpx.Response) -> RestoreFacesResult:
    return _restore_faces(response.content, _lower(response.headers))


def parse_id_photo(response: httpx.Response) -> IdPhotoResult:
    return _id_photo(response.content, _lower(response.headers))


def parse_select(response: httpx.Response) -> SelectResult:
    return _select(response.content, _lower(response.headers))


def parse_job_item(response: httpx.Response) -> JobItemResult:
    return JobItemResult(
        **_image_fields(response.content, _lower(response.headers)), headers=response.headers
    )
