"""The clients: :class:`Photos` (sync) and :class:`AsyncPhotos` (async).

Both only send what :mod:`photos_sh._requests` describes; the two classes
differ in nothing but ``async``/``await``. A test keeps their signatures equal.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from types import TracebackType
from typing import Optional, TypeVar, Union

import httpx

from . import _requests as r
from ._base import DEFAULT_MAX_RETRIES, BaseClient, Deadline, Timeout, connection_error
from ._requests import Request
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
)
from ._types import (
    Account,
    Align,
    BackgroundModel,
    BarcodeEngine,
    BarcodesResult,
    BlurMode,
    CaptionDetail,
    CaptionResult,
    CheckResult,
    CropFocus,
    Curves,
    FacesResult,
    Fit,
    Format,
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
    Pick,
    Point,
    Preset,
    Rect,
    Region,
    Shadow,
    TextResult,
    VectorizeMode,
    WatermarkPosition,
    WebhookSecret,
)

T = TypeVar("T")


class Jobs:
    """Batch jobs: one operation on many images, in the background."""

    def __init__(self, client: Photos) -> None:
        self._client = client

    def create(
        self,
        operation: str,
        *,
        urls: Optional[Sequence[str]] = None,
        images: Optional[Sequence[ImageInput]] = None,
        params: Optional[JobParams] = None,
        recipe: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Job:
        """Start a job that applies ``operation`` to every input.

        Inputs are ``urls`` the server fetches and/or ``images`` uploaded now
        (URLs come first in the job's items when both are given). ``params``
        are the operation's options, as a mapping or a query string; an
        option that repeats is a list.
        """
        return self._client._send(
            r.create_job(
                operation,
                urls=urls,
                images=images,
                params=params,
                recipe=recipe,
                webhook_url=webhook_url,
            )
        )

    def get(self, job_id: str) -> Job:
        """A job's status, progress and per-item results."""
        return self._client._send(r.get_job(job_id))

    def list(self) -> list[JobSummary]:
        """Your recent jobs, newest first (up to 100)."""
        return self._client._send(r.list_jobs())

    def delete(self, job_id: str) -> None:
        """Cancel a job if it is unfinished, and delete it and its results."""
        self._client._send(r.delete_job(job_id))

    def item(self, job_id: str, n: int) -> JobItemResult:
        """The result of item ``n`` (from 0) of a job, once that item is done."""
        return self._client._send(r.job_item(job_id, n))

    def wait(self, job_id: str, *, poll_interval: float = 2.0, timeout: float = 600.0) -> Job:
        """Poll until the job is completed and return it.

        Raises :class:`JobTimeoutError` after ``timeout`` seconds. A completed
        job may still have failed items: see ``job["counts"]``.
        """
        deadline = Deadline(timeout, poll_interval)
        while True:
            job = self.get(job_id)
            if job["status"] == "completed":
                return job
            self._client._sleep(deadline.next_pause(job))


class Photos(BaseClient):
    """The Photos.sh API, synchronously.

    The API key comes from ``api_key`` or the ``PHOTOS_API_KEY`` environment
    variable; the base URL from ``base_url``, ``PHOTOS_BASE_URL`` or
    ``https://api.photos.sh``. Requests that get ``503`` or cannot connect are
    sent again up to ``max_retries`` times.
    """

    jobs: Jobs

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[Timeout] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            has_http_client=http_client is not None,
        )
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client()
        self.jobs = Jobs(self)

    def close(self) -> None:
        """Close the HTTP client, unless it was supplied by the caller."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Photos:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _send(self, request: Request[T]) -> T:
        kwargs = self._request_kwargs(request)
        attempt = 0
        while True:
            try:
                response = self._http.request(**kwargs)
            except httpx.HTTPError as e:
                delay = self._delay_after_failure(request, attempt, e)
                if delay is None:
                    raise connection_error(e) from e
            else:
                delay = self._delay_after_response(request, attempt, response)
                if delay is None:
                    return self._finish(request, response)
            attempt += 1
            self._sleep(delay)

    # --- edit -------------------------------------------------------------------------

    def remove_background(
        self,
        image: ImageInput,
        *,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
        background: Optional[str] = None,
        crop: Optional[bool] = None,
        padding: Optional[int] = None,
        model: Optional[BackgroundModel] = None,
        studio: Optional[bool] = None,
        feather: Optional[float] = None,
        smooth: Optional[float] = None,
        shift: Optional[float] = None,
        hardness: Optional[float] = None,
        decontaminate: Optional[bool] = None,
        solidify: Optional[bool] = None,
        mask: Optional[bool] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fill: Optional[float] = None,
        align: Optional[Align] = None,
        shadow: Optional[Shadow] = None,
        reflection: Optional[bool] = None,
        blur: Optional[float] = None,
        background_image: Optional[ImageInput] = None,
    ) -> RemoveBackgroundResult:
        """Remove the background. PNG with transparency unless told otherwise.

        ``model`` picks the model that finds the subject; each costs the same,
        so try another when one drops part of what you sell. Left out, the API
        uses its default, ``"atlas"``:

        - ``"atlas"``: everyday product photos, a product alone or with its
          box, on any backdrop.
        - ``"lumen"``: pale packaging on a light backdrop, such as a cream or
          wooden box beside a bottle, and close-ups where the product fills
          the photo; on those, ``"atlas"`` can keep the bottle and drop the
          box. It may keep a dark backdrop at the photo's edge, and can cut
          away part of an open frame or wire stand.
        - ``"muse"``: people, in portraits and as models wearing the product.

        Another name is sent as it is, for models the API adds later.

        ``studio`` is for studio shots (a product on a plain, light backdrop,
        as in a light tent): it also keeps what clearly stands out from the
        backdrop and touches the product, such as the gift box, case or lid
        shown with a bottle, or a pale box the model left half transparent.
        Shadows and the floor below the product are left out. A photo without
        a plain light backdrop is cut out as without it.

        Six options change the cutout's edge. Each is sent only when given;
        ``feather=0`` and ``decontaminate=False`` are values, and are sent:

        - ``feather``: how soft the edge is, a blur of this many pixels across
          it, 0 to 10. 0 is the model's hard edge. Left out, it grows with the
          photo: 0.7 pixels for every 1000 of its long side.
        - ``smooth``: irons out ripples in the outline, 0 (the API's default)
          to 10. From about 4 it rounds small corners and breaks up thin
          parts, such as a wire stand.
        - ``shift``: moves the edge, in pixels, -10 to 10 (the API's default
          is 0): inward when negative, outward when positive. A small negative
          shift trims the light rim a dark subject shows on a dark background.
        - ``hardness``: narrows the edge, after the feather: 0 (the API's
          default) to 100, where it is about a pixel wide. On a dark
          background, pair it with a small negative ``shift``.
        - ``decontaminate``: cleans the old background's colour out of the
          soft edge. The API's default is ``True``; ``False`` keeps the
          photo's own colours there.
        - ``solidify``: makes semi-transparent areas inside the subject
          opaque, for an opaque product the model was unsure about in places.
          Wrong for glass, smoke or hair.

        The cutout can be staged in the same call: ``width`` and ``height``
        place the subject on a canvas, ``shadow`` and ``reflection`` go under
        it, and behind it goes one of ``background`` (a colour),
        ``background_image`` or ``blur`` (the photo's own background, blurred).
        """
        return self._send(
            r.remove_background(
                image,
                format=format,
                quality=quality,
                background=background,
                crop=crop,
                padding=padding,
                model=model,
                studio=studio,
                feather=feather,
                smooth=smooth,
                shift=shift,
                hardness=hardness,
                decontaminate=decontaminate,
                solidify=solidify,
                mask=mask,
                width=width,
                height=height,
                fill=fill,
                align=align,
                shadow=shadow,
                reflection=reflection,
                blur=blur,
                background_image=background_image,
            )
        )

    def resize(
        self,
        image: ImageInput,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fit: Optional[Fit] = None,
        enlarge: Optional[bool] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
        max_bytes: Optional[int] = None,
        background: Optional[str] = None,
        trim: Optional[bool] = None,
        trim_tolerance: Optional[int] = None,
        dpi: Optional[int] = None,
    ) -> ImageResult:
        """Resize, convert and compress. ``trim`` cuts away an even border first."""
        return self._send(
            r.resize(
                image,
                width=width,
                height=height,
                fit=fit,
                enlarge=enlarge,
                format=format,
                quality=quality,
                max_bytes=max_bytes,
                background=background,
                trim=trim,
                trim_tolerance=trim_tolerance,
                dpi=dpi,
            )
        )

    def upscale(
        self,
        image: ImageInput,
        *,
        scale: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """AI upscale, by ``scale`` (1 to 4, default 4)."""
        return self._send(r.upscale(image, scale=scale, format=format, quality=quality))

    def erase(
        self,
        image: ImageInput,
        *,
        rect: Union[Rect, Sequence[Rect], None] = None,
        mask: Optional[ImageInput] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Remove objects by inpainting.

        The area is ``rect`` (one ``(x, y, width, height)`` or several) and/or
        ``mask``: an image the size of the photo, white where to remove.
        """
        return self._send(r.erase(image, rect=rect, mask=mask, format=format, quality=quality))

    def remove_text(
        self,
        image: ImageInput,
        *,
        region: Optional[Region] = None,
        matching: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> RemoveTextResult:
        """Remove text, watermarks and captions (by default only off the product)."""
        return self._send(
            r.remove_text(image, region=region, matching=matching, format=format, quality=quality)
        )

    def run(
        self,
        image: ImageInput,
        *,
        preset: Optional[str] = None,
        recipe: Optional[str] = None,
    ) -> ImageResult:
        """Apply a built-in ``preset`` (by name) or a ``recipe`` (TOML text).

        A recipe's ``[barcodes]`` and ``[text]`` steps fill the result's
        ``barcodes`` and ``text``.
        """
        return self._send(r.run(image, preset=preset, recipe=recipe))

    def enhance(
        self,
        image: ImageInput,
        *,
        auto: Optional[bool] = None,
        levels: Optional[bool] = None,
        white_balance: Optional[bool] = None,
        brightness: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
        temperature: Optional[float] = None,
        sharpen: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Fix light and colour: automatically, or with only the settings given."""
        return self._send(
            r.enhance(
                image,
                auto=auto,
                levels=levels,
                white_balance=white_balance,
                brightness=brightness,
                contrast=contrast,
                saturation=saturation,
                temperature=temperature,
                sharpen=sharpen,
                format=format,
                quality=quality,
            )
        )

    def crop(
        self,
        image: ImageInput,
        *,
        aspect: Union[str, float, None] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        zoom: Optional[bool] = None,
        padding: Optional[float] = None,
        focus: Optional[CropFocus] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> CropResult:
        """Crop to a shape around the subject, or around the faces with ``focus="face"``.

        The shape is ``aspect`` (``"4:5"`` or a number), or ``width`` and
        ``height``, which also scale the crop to that size.
        """
        return self._send(
            r.crop(
                image,
                aspect=aspect,
                width=width,
                height=height,
                zoom=zoom,
                padding=padding,
                focus=focus,
                format=format,
                quality=quality,
            )
        )

    def watermark(
        self,
        image: ImageInput,
        *,
        text: Optional[str] = None,
        watermark: Optional[ImageInput] = None,
        color: Optional[str] = None,
        position: Optional[WatermarkPosition] = None,
        scale: Optional[float] = None,
        opacity: Optional[float] = None,
        margin: Optional[float] = None,
        tile: Optional[bool] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Add a mark: ``text``, or ``watermark``, an image such as a logo."""
        return self._send(
            r.watermark(
                image,
                text=text,
                watermark=watermark,
                color=color,
                position=position,
                scale=scale,
                opacity=opacity,
                margin=margin,
                tile=tile,
                format=format,
                quality=quality,
            )
        )

    def expand(
        self,
        image: ImageInput,
        *,
        aspect: Union[str, float, None] = None,
        left: Optional[int] = None,
        right: Optional[int] = None,
        top: Optional[int] = None,
        bottom: Optional[int] = None,
        fill: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Add room around the photo: to a shape (``aspect``), or by pixels on each side.

        The new area continues the photo unless ``fill`` is a colour.
        """
        return self._send(
            r.expand(
                image,
                aspect=aspect,
                left=left,
                right=right,
                top=top,
                bottom=bottom,
                fill=fill,
                format=format,
                quality=quality,
            )
        )

    def vectorize(
        self,
        image: ImageInput,
        *,
        mode: Optional[VectorizeMode] = None,
        curves: Optional[Curves] = None,
        detail: Optional[int] = None,
        speckle: Optional[int] = None,
    ) -> VectorizeResult:
        """Trace a logo, an icon or a flat drawing into SVG."""
        return self._send(
            r.vectorize(image, mode=mode, curves=curves, detail=detail, speckle=speckle)
        )

    def blur_faces(
        self,
        image: ImageInput,
        *,
        mode: Optional[BlurMode] = None,
        strength: Optional[float] = None,
        padding: Optional[float] = None,
        color: Optional[str] = None,
        min_score: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> BlurFacesResult:
        """Hide every face: blurred, pixelated, or covered with a colour."""
        return self._send(
            r.blur_faces(
                image,
                mode=mode,
                strength=strength,
                padding=padding,
                color=color,
                min_score=min_score,
                format=format,
                quality=quality,
            )
        )

    def id_photo(
        self,
        image: ImageInput,
        *,
        document: Optional[str] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        head_min_mm: Optional[float] = None,
        head_max_mm: Optional[float] = None,
        eyes_min_mm: Optional[float] = None,
        eyes_max_mm: Optional[float] = None,
        dpi: Optional[int] = None,
        background: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> IdPhotoResult:
        """Frame a portrait for an identity document.

        Give a ``document`` (see :meth:`id_photos`) or the sizes yourself. The
        photo's own background is kept unless ``background`` says otherwise.
        """
        return self._send(
            r.id_photo(
                image,
                document=document,
                width_mm=width_mm,
                height_mm=height_mm,
                head_min_mm=head_min_mm,
                head_max_mm=head_max_mm,
                eyes_min_mm=eyes_min_mm,
                eyes_max_mm=eyes_max_mm,
                dpi=dpi,
                background=background,
                format=format,
                quality=quality,
            )
        )

    def denoise(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Remove noise and JPEG artefacts. Slow without a GPU; up to 12 megapixels."""
        return self._send(r.denoise(image, strength=strength, format=format, quality=quality))

    def colorize(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Colour a black-and-white photo. The colours are guesses."""
        return self._send(r.colorize(image, strength=strength, format=format, quality=quality))

    def select(
        self,
        image: ImageInput,
        *,
        point: Union[Point, Sequence[Point], None] = None,
        exclude: Union[Point, Sequence[Point], None] = None,
        box: Optional[Rect] = None,
        pick: Optional[Pick] = None,
        mask: Optional[bool] = None,
        crop: Optional[bool] = None,
        padding: Optional[int] = None,
        background: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> SelectResult:
        """Cut out the object at a point or in a box.

        ``point`` is one ``(x, y)`` on the object or several, ``exclude`` the
        points that must stay outside it, and ``box`` an
        ``(x, y, width, height)`` around it. Give ``point`` and/or ``box``.
        """
        return self._send(
            r.select(
                image,
                point=point,
                exclude=exclude,
                box=box,
                pick=pick,
                mask=mask,
                crop=crop,
                padding=padding,
                background=background,
                format=format,
                quality=quality,
            )
        )

    def restore_faces(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        min_score: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> RestoreFacesResult:
        """Redraw the faces in an old or poor photo. The detail is invented."""
        return self._send(
            r.restore_faces(
                image, strength=strength, min_score=min_score, format=format, quality=quality
            )
        )

    # --- check and fix ----------------------------------------------------------------

    def fix(self, image: ImageInput, marketplace: str) -> FixResult:
        """Make a photo meet a marketplace's rules, and check the result."""
        return self._send(r.fix(image, marketplace))

    def check(
        self,
        image: ImageInput,
        *,
        marketplace: Optional[str] = None,
        subject: Optional[bool] = None,
        text: Optional[bool] = None,
    ) -> CheckResult:
        """Check photo quality and, with ``marketplace``, that marketplace's rules."""
        return self._send(r.check(image, marketplace=marketplace, subject=subject, text=text))

    # --- read -------------------------------------------------------------------------

    def read_barcodes(
        self,
        image: ImageInput,
        *,
        all_formats: Optional[bool] = None,
        engine: Optional[BarcodeEngine] = None,
    ) -> BarcodesResult:
        """Read barcodes (retail codes by default; ``all_formats`` adds QR and others)."""
        return self._send(r.read_barcodes(image, all_formats=all_formats, engine=engine))

    def read_text(self, image: ImageInput) -> TextResult:
        """Read the text in a photo (OCR), top to bottom."""
        return self._send(r.read_text(image))

    def read_label(self, images: Union[ImageInput, Sequence[ImageInput]]) -> LabelResult:
        """Read product details from 1 to 8 photos of one product's label."""
        return self._send(r.read_label(images))

    def identify(
        self,
        images: Union[ImageInput, Sequence[ImageInput]],
        *,
        catalogue: Optional[str] = None,
        top: Optional[int] = None,
    ) -> IdentifyResult:
        """Match 1 to 8 photos of one product against one of your catalogues.

        The catalogues are your organisation's own, uploaded on the console's
        Catalogues page. Catalogue matching is turned on per organisation:
        until it is on for yours and a catalogue is uploaded, the API answers
        404 (``NotFoundError``).
        ``catalogue`` may be left out when you have exactly one.
        """
        return self._send(r.identify(images, catalogue=catalogue, top=top))

    def palette(self, image: ImageInput, *, colors: Optional[int] = None) -> PaletteResult:
        """The main colours of an image, the most common first."""
        return self._send(r.palette(image, colors=colors))

    def find_faces(self, image: ImageInput, *, min_score: Optional[float] = None) -> FacesResult:
        """Where the faces are: a box and five landmarks each. Not whose they are."""
        return self._send(r.find_faces(image, min_score=min_score))

    def caption(
        self, image: ImageInput, *, detail: Optional[CaptionDetail] = None
    ) -> CaptionResult:
        """Describe the photo in English. It can be wrong: read it before publishing it."""
        return self._send(r.caption(image, detail=detail))

    # --- account and service ----------------------------------------------------------

    def account(self) -> Account:
        """The caller's account, credits and prices."""
        return self._send(r.account())

    def presets(self) -> list[Preset]:
        """The built-in presets for :meth:`run`."""
        return self._send(r.presets())

    def preset(self, name: str) -> str:
        """A built-in preset's recipe, as TOML text: a start for your own ``recipe``."""
        return self._send(r.preset(name))

    def marketplaces(self) -> list[MarketplaceProfile]:
        """Each marketplace's image rules and what :meth:`fix` produces."""
        return self._send(r.marketplaces())

    def id_photos(self) -> list[IdPhotoDocument]:
        """The documents with built-in photo rules, for :meth:`id_photo`."""
        return self._send(r.id_photos())

    def webhook_secret(self) -> WebhookSecret:
        """The key your webhooks are signed with (see :mod:`photos_sh.webhooks`)."""
        return self._send(r.webhook_secret())

    def health(self) -> HealthStatus:
        """``"ok"``, ``"loading"`` or ``"failed"``. Not ready is not an error here."""
        return self._send(r.health())


class AsyncJobs:
    """Batch jobs: one operation on many images, in the background."""

    def __init__(self, client: AsyncPhotos) -> None:
        self._client = client

    async def create(
        self,
        operation: str,
        *,
        urls: Optional[Sequence[str]] = None,
        images: Optional[Sequence[ImageInput]] = None,
        params: Optional[JobParams] = None,
        recipe: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Job:
        """Start a job that applies ``operation`` to every input.

        Inputs are ``urls`` the server fetches and/or ``images`` uploaded now
        (URLs come first in the job's items when both are given). ``params``
        are the operation's options, as a mapping or a query string; an
        option that repeats is a list.
        """
        return await self._client._send(
            r.create_job(
                operation,
                urls=urls,
                images=images,
                params=params,
                recipe=recipe,
                webhook_url=webhook_url,
            )
        )

    async def get(self, job_id: str) -> Job:
        """A job's status, progress and per-item results."""
        return await self._client._send(r.get_job(job_id))

    async def list(self) -> list[JobSummary]:
        """Your recent jobs, newest first (up to 100)."""
        return await self._client._send(r.list_jobs())

    async def delete(self, job_id: str) -> None:
        """Cancel a job if it is unfinished, and delete it and its results."""
        await self._client._send(r.delete_job(job_id))

    async def item(self, job_id: str, n: int) -> JobItemResult:
        """The result of item ``n`` (from 0) of a job, once that item is done."""
        return await self._client._send(r.job_item(job_id, n))

    async def wait(self, job_id: str, *, poll_interval: float = 2.0, timeout: float = 600.0) -> Job:
        """Poll until the job is completed and return it.

        Raises :class:`JobTimeoutError` after ``timeout`` seconds. A completed
        job may still have failed items: see ``job["counts"]``.
        """
        deadline = Deadline(timeout, poll_interval)
        while True:
            job = await self.get(job_id)
            if job["status"] == "completed":
                return job
            await self._client._sleep(deadline.next_pause(job))


class AsyncPhotos(BaseClient):
    """The Photos.sh API, for asyncio.

    The API key comes from ``api_key`` or the ``PHOTOS_API_KEY`` environment
    variable; the base URL from ``base_url``, ``PHOTOS_BASE_URL`` or
    ``https://api.photos.sh``. Requests that get ``503`` or cannot connect are
    sent again up to ``max_retries`` times.
    """

    jobs: AsyncJobs

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[Timeout] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            has_http_client=http_client is not None,
        )
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient()
        self.jobs = AsyncJobs(self)

    async def aclose(self) -> None:
        """Close the HTTP client, unless it was supplied by the caller."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncPhotos:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _send(self, request: Request[T]) -> T:
        kwargs = self._request_kwargs(request)
        attempt = 0
        while True:
            try:
                response = await self._http.request(**kwargs)
            except httpx.HTTPError as e:
                delay = self._delay_after_failure(request, attempt, e)
                if delay is None:
                    raise connection_error(e) from e
            else:
                delay = self._delay_after_response(request, attempt, response)
                if delay is None:
                    return self._finish(request, response)
            attempt += 1
            await self._sleep(delay)

    # --- edit -------------------------------------------------------------------------

    async def remove_background(
        self,
        image: ImageInput,
        *,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
        background: Optional[str] = None,
        crop: Optional[bool] = None,
        padding: Optional[int] = None,
        model: Optional[BackgroundModel] = None,
        studio: Optional[bool] = None,
        feather: Optional[float] = None,
        smooth: Optional[float] = None,
        shift: Optional[float] = None,
        hardness: Optional[float] = None,
        decontaminate: Optional[bool] = None,
        solidify: Optional[bool] = None,
        mask: Optional[bool] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fill: Optional[float] = None,
        align: Optional[Align] = None,
        shadow: Optional[Shadow] = None,
        reflection: Optional[bool] = None,
        blur: Optional[float] = None,
        background_image: Optional[ImageInput] = None,
    ) -> RemoveBackgroundResult:
        """Remove the background. PNG with transparency unless told otherwise.

        ``model`` picks the model that finds the subject; each costs the same,
        so try another when one drops part of what you sell. Left out, the API
        uses its default, ``"atlas"``:

        - ``"atlas"``: everyday product photos, a product alone or with its
          box, on any backdrop.
        - ``"lumen"``: pale packaging on a light backdrop, such as a cream or
          wooden box beside a bottle, and close-ups where the product fills
          the photo; on those, ``"atlas"`` can keep the bottle and drop the
          box. It may keep a dark backdrop at the photo's edge, and can cut
          away part of an open frame or wire stand.
        - ``"muse"``: people, in portraits and as models wearing the product.

        Another name is sent as it is, for models the API adds later.

        ``studio`` is for studio shots (a product on a plain, light backdrop,
        as in a light tent): it also keeps what clearly stands out from the
        backdrop and touches the product, such as the gift box, case or lid
        shown with a bottle, or a pale box the model left half transparent.
        Shadows and the floor below the product are left out. A photo without
        a plain light backdrop is cut out as without it.

        Six options change the cutout's edge. Each is sent only when given;
        ``feather=0`` and ``decontaminate=False`` are values, and are sent:

        - ``feather``: how soft the edge is, a blur of this many pixels across
          it, 0 to 10. 0 is the model's hard edge. Left out, it grows with the
          photo: 0.7 pixels for every 1000 of its long side.
        - ``smooth``: irons out ripples in the outline, 0 (the API's default)
          to 10. From about 4 it rounds small corners and breaks up thin
          parts, such as a wire stand.
        - ``shift``: moves the edge, in pixels, -10 to 10 (the API's default
          is 0): inward when negative, outward when positive. A small negative
          shift trims the light rim a dark subject shows on a dark background.
        - ``hardness``: narrows the edge, after the feather: 0 (the API's
          default) to 100, where it is about a pixel wide. On a dark
          background, pair it with a small negative ``shift``.
        - ``decontaminate``: cleans the old background's colour out of the
          soft edge. The API's default is ``True``; ``False`` keeps the
          photo's own colours there.
        - ``solidify``: makes semi-transparent areas inside the subject
          opaque, for an opaque product the model was unsure about in places.
          Wrong for glass, smoke or hair.

        The cutout can be staged in the same call: ``width`` and ``height``
        place the subject on a canvas, ``shadow`` and ``reflection`` go under
        it, and behind it goes one of ``background`` (a colour),
        ``background_image`` or ``blur`` (the photo's own background, blurred).
        """
        return await self._send(
            r.remove_background(
                image,
                format=format,
                quality=quality,
                background=background,
                crop=crop,
                padding=padding,
                model=model,
                studio=studio,
                feather=feather,
                smooth=smooth,
                shift=shift,
                hardness=hardness,
                decontaminate=decontaminate,
                solidify=solidify,
                mask=mask,
                width=width,
                height=height,
                fill=fill,
                align=align,
                shadow=shadow,
                reflection=reflection,
                blur=blur,
                background_image=background_image,
            )
        )

    async def resize(
        self,
        image: ImageInput,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fit: Optional[Fit] = None,
        enlarge: Optional[bool] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
        max_bytes: Optional[int] = None,
        background: Optional[str] = None,
        trim: Optional[bool] = None,
        trim_tolerance: Optional[int] = None,
        dpi: Optional[int] = None,
    ) -> ImageResult:
        """Resize, convert and compress. ``trim`` cuts away an even border first."""
        return await self._send(
            r.resize(
                image,
                width=width,
                height=height,
                fit=fit,
                enlarge=enlarge,
                format=format,
                quality=quality,
                max_bytes=max_bytes,
                background=background,
                trim=trim,
                trim_tolerance=trim_tolerance,
                dpi=dpi,
            )
        )

    async def upscale(
        self,
        image: ImageInput,
        *,
        scale: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """AI upscale, by ``scale`` (1 to 4, default 4)."""
        return await self._send(r.upscale(image, scale=scale, format=format, quality=quality))

    async def erase(
        self,
        image: ImageInput,
        *,
        rect: Union[Rect, Sequence[Rect], None] = None,
        mask: Optional[ImageInput] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Remove objects by inpainting.

        The area is ``rect`` (one ``(x, y, width, height)`` or several) and/or
        ``mask``: an image the size of the photo, white where to remove.
        """
        return await self._send(
            r.erase(image, rect=rect, mask=mask, format=format, quality=quality)
        )

    async def remove_text(
        self,
        image: ImageInput,
        *,
        region: Optional[Region] = None,
        matching: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> RemoveTextResult:
        """Remove text, watermarks and captions (by default only off the product)."""
        return await self._send(
            r.remove_text(image, region=region, matching=matching, format=format, quality=quality)
        )

    async def run(
        self,
        image: ImageInput,
        *,
        preset: Optional[str] = None,
        recipe: Optional[str] = None,
    ) -> ImageResult:
        """Apply a built-in ``preset`` (by name) or a ``recipe`` (TOML text).

        A recipe's ``[barcodes]`` and ``[text]`` steps fill the result's
        ``barcodes`` and ``text``.
        """
        return await self._send(r.run(image, preset=preset, recipe=recipe))

    async def enhance(
        self,
        image: ImageInput,
        *,
        auto: Optional[bool] = None,
        levels: Optional[bool] = None,
        white_balance: Optional[bool] = None,
        brightness: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
        temperature: Optional[float] = None,
        sharpen: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Fix light and colour: automatically, or with only the settings given."""
        return await self._send(
            r.enhance(
                image,
                auto=auto,
                levels=levels,
                white_balance=white_balance,
                brightness=brightness,
                contrast=contrast,
                saturation=saturation,
                temperature=temperature,
                sharpen=sharpen,
                format=format,
                quality=quality,
            )
        )

    async def crop(
        self,
        image: ImageInput,
        *,
        aspect: Union[str, float, None] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        zoom: Optional[bool] = None,
        padding: Optional[float] = None,
        focus: Optional[CropFocus] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> CropResult:
        """Crop to a shape around the subject, or around the faces with ``focus="face"``.

        The shape is ``aspect`` (``"4:5"`` or a number), or ``width`` and
        ``height``, which also scale the crop to that size.
        """
        return await self._send(
            r.crop(
                image,
                aspect=aspect,
                width=width,
                height=height,
                zoom=zoom,
                padding=padding,
                focus=focus,
                format=format,
                quality=quality,
            )
        )

    async def watermark(
        self,
        image: ImageInput,
        *,
        text: Optional[str] = None,
        watermark: Optional[ImageInput] = None,
        color: Optional[str] = None,
        position: Optional[WatermarkPosition] = None,
        scale: Optional[float] = None,
        opacity: Optional[float] = None,
        margin: Optional[float] = None,
        tile: Optional[bool] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Add a mark: ``text``, or ``watermark``, an image such as a logo."""
        return await self._send(
            r.watermark(
                image,
                text=text,
                watermark=watermark,
                color=color,
                position=position,
                scale=scale,
                opacity=opacity,
                margin=margin,
                tile=tile,
                format=format,
                quality=quality,
            )
        )

    async def expand(
        self,
        image: ImageInput,
        *,
        aspect: Union[str, float, None] = None,
        left: Optional[int] = None,
        right: Optional[int] = None,
        top: Optional[int] = None,
        bottom: Optional[int] = None,
        fill: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Add room around the photo: to a shape (``aspect``), or by pixels on each side.

        The new area continues the photo unless ``fill`` is a colour.
        """
        return await self._send(
            r.expand(
                image,
                aspect=aspect,
                left=left,
                right=right,
                top=top,
                bottom=bottom,
                fill=fill,
                format=format,
                quality=quality,
            )
        )

    async def vectorize(
        self,
        image: ImageInput,
        *,
        mode: Optional[VectorizeMode] = None,
        curves: Optional[Curves] = None,
        detail: Optional[int] = None,
        speckle: Optional[int] = None,
    ) -> VectorizeResult:
        """Trace a logo, an icon or a flat drawing into SVG."""
        return await self._send(
            r.vectorize(image, mode=mode, curves=curves, detail=detail, speckle=speckle)
        )

    async def blur_faces(
        self,
        image: ImageInput,
        *,
        mode: Optional[BlurMode] = None,
        strength: Optional[float] = None,
        padding: Optional[float] = None,
        color: Optional[str] = None,
        min_score: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> BlurFacesResult:
        """Hide every face: blurred, pixelated, or covered with a colour."""
        return await self._send(
            r.blur_faces(
                image,
                mode=mode,
                strength=strength,
                padding=padding,
                color=color,
                min_score=min_score,
                format=format,
                quality=quality,
            )
        )

    async def id_photo(
        self,
        image: ImageInput,
        *,
        document: Optional[str] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        head_min_mm: Optional[float] = None,
        head_max_mm: Optional[float] = None,
        eyes_min_mm: Optional[float] = None,
        eyes_max_mm: Optional[float] = None,
        dpi: Optional[int] = None,
        background: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> IdPhotoResult:
        """Frame a portrait for an identity document.

        Give a ``document`` (see :meth:`id_photos`) or the sizes yourself. The
        photo's own background is kept unless ``background`` says otherwise.
        """
        return await self._send(
            r.id_photo(
                image,
                document=document,
                width_mm=width_mm,
                height_mm=height_mm,
                head_min_mm=head_min_mm,
                head_max_mm=head_max_mm,
                eyes_min_mm=eyes_min_mm,
                eyes_max_mm=eyes_max_mm,
                dpi=dpi,
                background=background,
                format=format,
                quality=quality,
            )
        )

    async def denoise(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Remove noise and JPEG artefacts. Slow without a GPU; up to 12 megapixels."""
        return await self._send(r.denoise(image, strength=strength, format=format, quality=quality))

    async def colorize(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> ImageResult:
        """Colour a black-and-white photo. The colours are guesses."""
        return await self._send(
            r.colorize(image, strength=strength, format=format, quality=quality)
        )

    async def select(
        self,
        image: ImageInput,
        *,
        point: Union[Point, Sequence[Point], None] = None,
        exclude: Union[Point, Sequence[Point], None] = None,
        box: Optional[Rect] = None,
        pick: Optional[Pick] = None,
        mask: Optional[bool] = None,
        crop: Optional[bool] = None,
        padding: Optional[int] = None,
        background: Optional[str] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> SelectResult:
        """Cut out the object at a point or in a box.

        ``point`` is one ``(x, y)`` on the object or several, ``exclude`` the
        points that must stay outside it, and ``box`` an
        ``(x, y, width, height)`` around it. Give ``point`` and/or ``box``.
        """
        return await self._send(
            r.select(
                image,
                point=point,
                exclude=exclude,
                box=box,
                pick=pick,
                mask=mask,
                crop=crop,
                padding=padding,
                background=background,
                format=format,
                quality=quality,
            )
        )

    async def restore_faces(
        self,
        image: ImageInput,
        *,
        strength: Optional[float] = None,
        min_score: Optional[float] = None,
        format: Optional[Format] = None,
        quality: Optional[int] = None,
    ) -> RestoreFacesResult:
        """Redraw the faces in an old or poor photo. The detail is invented."""
        return await self._send(
            r.restore_faces(
                image, strength=strength, min_score=min_score, format=format, quality=quality
            )
        )

    # --- check and fix ----------------------------------------------------------------

    async def fix(self, image: ImageInput, marketplace: str) -> FixResult:
        """Make a photo meet a marketplace's rules, and check the result."""
        return await self._send(r.fix(image, marketplace))

    async def check(
        self,
        image: ImageInput,
        *,
        marketplace: Optional[str] = None,
        subject: Optional[bool] = None,
        text: Optional[bool] = None,
    ) -> CheckResult:
        """Check photo quality and, with ``marketplace``, that marketplace's rules."""
        return await self._send(r.check(image, marketplace=marketplace, subject=subject, text=text))

    # --- read -------------------------------------------------------------------------

    async def read_barcodes(
        self,
        image: ImageInput,
        *,
        all_formats: Optional[bool] = None,
        engine: Optional[BarcodeEngine] = None,
    ) -> BarcodesResult:
        """Read barcodes (retail codes by default; ``all_formats`` adds QR and others)."""
        return await self._send(r.read_barcodes(image, all_formats=all_formats, engine=engine))

    async def read_text(self, image: ImageInput) -> TextResult:
        """Read the text in a photo (OCR), top to bottom."""
        return await self._send(r.read_text(image))

    async def read_label(self, images: Union[ImageInput, Sequence[ImageInput]]) -> LabelResult:
        """Read product details from 1 to 8 photos of one product's label."""
        return await self._send(r.read_label(images))

    async def identify(
        self,
        images: Union[ImageInput, Sequence[ImageInput]],
        *,
        catalogue: Optional[str] = None,
        top: Optional[int] = None,
    ) -> IdentifyResult:
        """Match 1 to 8 photos of one product against one of your catalogues.

        The catalogues are your organisation's own, uploaded on the console's
        Catalogues page. Catalogue matching is turned on per organisation:
        until it is on for yours and a catalogue is uploaded, the API answers
        404 (``NotFoundError``).
        ``catalogue`` may be left out when you have exactly one.
        """
        return await self._send(r.identify(images, catalogue=catalogue, top=top))

    async def palette(self, image: ImageInput, *, colors: Optional[int] = None) -> PaletteResult:
        """The main colours of an image, the most common first."""
        return await self._send(r.palette(image, colors=colors))

    async def find_faces(
        self, image: ImageInput, *, min_score: Optional[float] = None
    ) -> FacesResult:
        """Where the faces are: a box and five landmarks each. Not whose they are."""
        return await self._send(r.find_faces(image, min_score=min_score))

    async def caption(
        self, image: ImageInput, *, detail: Optional[CaptionDetail] = None
    ) -> CaptionResult:
        """Describe the photo in English. It can be wrong: read it before publishing it."""
        return await self._send(r.caption(image, detail=detail))

    # --- account and service ----------------------------------------------------------

    async def account(self) -> Account:
        """The caller's account, credits and prices."""
        return await self._send(r.account())

    async def presets(self) -> list[Preset]:
        """The built-in presets for :meth:`run`."""
        return await self._send(r.presets())

    async def preset(self, name: str) -> str:
        """A built-in preset's recipe, as TOML text: a start for your own ``recipe``."""
        return await self._send(r.preset(name))

    async def marketplaces(self) -> list[MarketplaceProfile]:
        """Each marketplace's image rules and what :meth:`fix` produces."""
        return await self._send(r.marketplaces())

    async def id_photos(self) -> list[IdPhotoDocument]:
        """The documents with built-in photo rules, for :meth:`id_photo`."""
        return await self._send(r.id_photos())

    async def webhook_secret(self) -> WebhookSecret:
        """The key your webhooks are signed with (see :mod:`photos_sh.webhooks`)."""
        return await self._send(r.webhook_secret())

    async def health(self) -> HealthStatus:
        """``"ok"``, ``"loading"`` or ``"failed"``. Not ready is not an error here."""
        return await self._send(r.health())
