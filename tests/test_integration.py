"""Against a real engine. Skipped unless both variables are set:

PHOTOS_TEST_BASE_URL=http://127.0.0.1:8098/api PHOTOS_TEST_API_KEY=... uv run pytest

Most tests run with both clients and use no model. The ones that need a model
worker run once each, on small images (512 pixels at most).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import struct
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from conftest import BOXED, DATA, PNG, LocalServer, Reply

from photos_sh import (
    APIError,
    AsyncPhotos,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    Photos,
    PhotosError,
    UnprocessableError,
    webhooks,
)

BASE_URL = os.environ.get("PHOTOS_TEST_BASE_URL", "")
API_KEY = os.environ.get("PHOTOS_TEST_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not (BASE_URL and API_KEY),
    reason="set PHOTOS_TEST_BASE_URL and PHOTOS_TEST_API_KEY to run against an engine",
)

# The engine is shared: wait out a busy worker rather than fail.
OPTIONS: dict[str, Any] = {"max_retries": 6}

# NASA's portrait of astronaut Eileen Collins (public domain), 512 x 512: one face.
PORTRAIT = DATA / "portrait.jpg"


def png_size(content: bytes) -> tuple[int, int]:
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", content[16:24])
    return width, height


@dataclass
class Live:
    """Runs a call with the sync or the async client against the engine."""

    kind: str
    api_key: str = API_KEY

    def run(self, call: Callable[[Any], Any]) -> Any:
        if self.kind == "sync":
            with Photos(self.api_key, base_url=BASE_URL, **OPTIONS) as client:
                return call(client)

        async def go() -> Any:
            async with AsyncPhotos(self.api_key, base_url=BASE_URL, **OPTIONS) as client:
                result = call(client)
                return await result if inspect.isawaitable(result) else result

        return asyncio.run(go())


@pytest.fixture(params=["sync", "async"])
def live(request: pytest.FixtureRequest) -> Live:
    return Live(request.param)


# --- no model needed: both clients ----------------------------------------------------


def test_health(live: Live) -> None:
    assert live.run(lambda c: c.health()) == "ok"


def test_account(live: Live) -> None:
    account = live.run(lambda c: c.account())
    assert isinstance(account["account"], str)
    assert account.get("unlimited") is True or isinstance(account.get("credits"), int)


def test_presets_and_marketplaces(live: Live) -> None:
    presets = live.run(lambda c: c.presets())
    assert "web" in [p["name"] for p in presets]
    assert all(p["description"] for p in presets)

    marketplaces = live.run(lambda c: c.marketplaces())
    amazon = next(m for m in marketplaces if m["name"] == "amazon")
    assert amazon["title"]
    assert isinstance(amazon["rules"], list)
    assert isinstance(amazon["fix"], dict)
    assert isinstance(amazon["sources"], list)


def test_webhook_secret(live: Live) -> None:
    secret = live.run(lambda c: c.webhook_secret())
    assert secret["secret"].startswith("whsec_")
    assert secret["header"] == "Photos-Signature"
    assert secret["scheme"]


def test_resize(live: Live) -> None:
    result = live.run(lambda c: c.resize(PNG, width=32, format="png"))
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (32, 24) == png_size(result.content)
    assert result.quality is None
    assert result.server_timing

    jpeg = live.run(
        lambda c: c.resize(
            PNG, width=40, height=40, fit="cover", format="jpg", quality=70, enlarge=False
        )
    )
    assert jpeg.content_type == "image/jpeg"
    assert jpeg.content[:2] == b"\xff\xd8"
    assert (jpeg.width, jpeg.height, jpeg.quality) == (40, 40, 70)


def test_resize_from_a_path(live: Live) -> None:
    result = live.run(lambda c: c.resize(DATA / "label.png", width=90, format="webp"))
    assert result.content_type == "image/webp"
    assert result.width == 90


def test_run_with_a_recipe(live: Live) -> None:
    recipe = '[output]\nformat = "jpg"\nquality = 60\nmax_side = 32\n'
    result = live.run(lambda c: c.run(PNG, recipe=recipe))
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height, result.quality) == (32, 24, 60)

    with pytest.raises(UnprocessableError) as caught:
        live.run(lambda c: c.run(PNG, recipe="this is not TOML"))
    assert (caught.value.status, caught.value.code) == (422, "unprocessable")


def test_run_with_a_preset(live: Live) -> None:
    result = live.run(lambda c: c.run(PNG, preset="web"))  # no model in this preset
    assert result.content_type == "image/webp"
    assert (result.width, result.height) == (64, 48)


def test_check_quality_only(live: Live) -> None:
    report = live.run(lambda c: c.check(PNG))
    assert report["metrics"]["width"] == 64
    assert report["metrics"]["height"] == 48
    assert isinstance(report["findings"], list)
    for finding in report["findings"]:
        assert {"code", "severity", "message"} <= set(finding)


def test_read_barcodes(live: Live) -> None:
    result = live.run(lambda c: c.read_barcodes(PNG, all_formats=True, engine="auto"))
    assert result["barcodes"] == []
    assert isinstance(result["variant"], str)


def test_resize_trim_and_dpi(live: Live) -> None:
    trimmed = live.run(lambda c: c.resize(BOXED, trim=True, format="png"))
    assert (trimmed.width, trimmed.height) == (40, 20) == png_size(trimmed.content)

    printed = live.run(lambda c: c.resize(BOXED, dpi=300, format="png"))
    assert (printed.width, printed.height) == (100, 80)
    assert b"pHYs" + struct.pack(">I", 11811) in printed.content  # 300 dpi, per metre


def test_enhance(live: Live) -> None:
    result = live.run(lambda c: c.enhance(PNG, format="png"))
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (64, 48) == png_size(result.content)

    grey = live.run(lambda c: c.enhance(PNG, saturation=-100, sharpen=20, format="jpg"))
    assert grey.content_type == "image/jpeg"
    assert (grey.width, grey.height) == (64, 48)


def test_watermark(live: Live) -> None:
    text = live.run(
        lambda c: c.watermark(BOXED, text="photos.sh", color="black", opacity=100, scale=50)
    )
    assert text.content_type == "image/png"
    assert (text.width, text.height) == (100, 80) == png_size(text.content)

    logo = live.run(
        lambda c: c.watermark(BOXED, watermark=PNG, position="top-left", scale=20, margin=0)
    )
    assert (logo.width, logo.height) == (100, 80)
    assert logo.content != text.content

    with pytest.raises(BadRequestError):
        live.run(lambda c: c.watermark(BOXED, text="a", position="middle"))


def test_expand_with_a_colour(live: Live) -> None:
    square = live.run(lambda c: c.expand(BOXED, aspect="1:1", fill="white"))
    assert (square.width, square.height) == (100, 100) == png_size(square.content)

    wider = live.run(lambda c: c.expand(BOXED, left=10, bottom=5, fill="#ff0000"))
    assert (wider.width, wider.height) == (110, 85)


def test_vectorize(live: Live) -> None:
    traced = live.run(lambda c: c.vectorize(BOXED))
    assert traced.content_type == "image/svg+xml"
    assert traced.content.startswith(b"<svg ")
    assert (traced.width, traced.height) == (100, 80)
    assert traced.paths == 2  # the white, and the box

    mono = live.run(lambda c: c.vectorize(BOXED, mode="mono", curves="polygon"))
    assert mono.paths == 1


def test_palette(live: Live) -> None:
    palette = live.run(lambda c: c.palette(BOXED, colors=2))
    assert (palette["width"], palette["height"]) == (100, 80)
    assert [colour["hex"] for colour in palette["colors"]] == ["#ffffff", "#141ec8"]
    assert palette["colors"][1]["rgb"] == [20, 30, 200]
    assert palette["colors"][1]["share"] == 0.1


def test_id_photos(live: Live) -> None:
    documents = live.run(lambda c: c.id_photos())
    assert "us-passport" in [document["name"] for document in documents]
    uk = next(document for document in documents if document["name"] == "uk-passport")
    assert uk["title"]
    assert (uk["width_mm"], uk["height_mm"]) == (35, 45)
    assert uk["head_min_mm"] < uk["head_max_mm"]
    assert uk["background"]
    assert uk["sources"][0].startswith("https://")
    assert isinstance(uk["notes"], list)
    assert len(uk["checked"]) == 10  # a date


def test_errors(live: Live) -> None:
    with pytest.raises(BadRequestError) as bad:
        live.run(lambda c: c.resize(PNG, fit="cover", width=10))
    assert (bad.value.status, bad.value.code) == (400, "bad_request")
    assert "width and height" in bad.value.message

    with pytest.raises(BadRequestError):
        live.run(lambda c: c.resize(b"this is not an image", width=10))

    with pytest.raises(NotFoundError) as missing:
        live.run(lambda c: c.jobs.get("job_does_not_exist"))
    assert (missing.value.status, missing.value.code) == (404, "not_found")

    with pytest.raises(AuthenticationError) as denied:
        Live(live.kind, api_key="wrong-key").run(lambda c: c.account())
    assert (denied.value.status, denied.value.code) == (401, "unauthorized")


def test_a_wrong_base_url_is_a_plain_api_error(live: Live) -> None:
    def call() -> Any:
        if live.kind == "sync":
            with Photos(API_KEY, base_url=BASE_URL + "/nowhere") as client:
                return client.account()

        async def go() -> Any:
            async with AsyncPhotos(API_KEY, base_url=BASE_URL + "/nowhere") as client:
                return await client.account()

        return asyncio.run(go())

    with pytest.raises(APIError) as caught:
        call()
    assert type(caught.value) is APIError
    assert (caught.value.status, caught.value.code) == (404, None)


def test_a_failed_job_item(live: Live, server: LocalServer) -> None:
    server.replies = [Reply(404)]
    job = live.run(lambda c: c.jobs.create("resize", urls=[server.url + "/gone.png"]))
    try:
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.2, timeout=120))
        assert done["counts"]["failed"] == 1
        item = done["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "input_unavailable"
        assert item["error"]["message"]
        with pytest.raises(NotFoundError):
            live.run(lambda c: c.jobs.item(job["id"], 0))
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


def test_job_with_uploads(live: Live) -> None:
    job = live.run(
        lambda c: c.jobs.create(
            "resize",
            images=[PNG, DATA / "label.png"],
            params={"width": 16, "format": "png", "enlarge": False},
        )
    )
    try:
        assert job["id"].startswith("job_")
        assert job["operation"] == "resize"
        assert job["params"] == "width=16&format=png&enlarge=false"
        assert job["counts"]["total"] == 2
        assert [item["input"] for item in job["items"]] == ["image-1", "label.png"]

        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.2, timeout=120))
        assert done["status"] == "completed"
        assert done["counts"] == {"total": 2, "done": 2, "failed": 0, "pending": 0}
        assert done["items"][0]["result"].endswith(f"/v1/jobs/{job['id']}/items/0")
        assert done["items"][0]["content_type"] == "image/png"

        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        assert item.is_image
        assert item.content_type == "image/png"
        assert (item.width, item.height) == (16, 12) == png_size(item.content)
        assert item.headers["x-image-width"] == "16"

        with pytest.raises(NotFoundError):
            live.run(lambda c: c.jobs.item(job["id"], 7))

        listed = live.run(lambda c: c.jobs.list())
        assert job["id"] in [summary["id"] for summary in listed]
    finally:
        assert live.run(lambda c: c.jobs.delete(job["id"])) is None
    with pytest.raises(NotFoundError):
        live.run(lambda c: c.jobs.get(job["id"]))


def test_job_with_uploads_and_a_recipe(live: Live) -> None:
    recipe = '[output]\nformat = "jpg"\nmax_side = 16\n'
    job = live.run(lambda c: c.jobs.create("run", images=[PNG], recipe=recipe))
    try:
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.2, timeout=120))
        assert done["counts"]["done"] == 1, done["items"]
        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        assert (item.content_type, item.width, item.height) == ("image/jpeg", 16, 12)
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


def test_fix_job_item_has_the_verdict(live: Live) -> None:
    """Newer engines keep the fix and remove-text headers on job items."""
    if live.kind == "async":
        pytest.skip("one model job is enough: the sync run covers it")
    job = live.run(lambda c: c.jobs.create("fix", images=[PNG], params={"marketplace": "etsy"}))
    try:
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.5, timeout=300))
        assert done["counts"]["done"] == 1, done["items"]
        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        if "x-marketplace-passed" not in item.headers:
            with pytest.raises(PhotosError, match="x-marketplace-passed"):
                item.fix()
            pytest.skip("this engine does not keep x-marketplace-* on job items")
        fixed = item.fix()
        assert isinstance(fixed.passed, bool)
        assert isinstance(fixed.findings, list)
        assert fixed.passed == (done["items"][0]["headers"]["x-marketplace-passed"] == "true")
        assert (fixed.width, fixed.height) == (item.width, item.height)
        assert fixed.content == item.content
        with pytest.raises(PhotosError, match="x-text-removed"):
            item.remove_text()
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


def test_remove_text_job_item_has_the_counts(live: Live) -> None:
    if live.kind == "sync":
        pytest.skip("one model job is enough: the async run covers it")
    job = live.run(
        lambda c: c.jobs.create(
            "remove-text", images=[DATA / "label.png"], params={"region": "all", "format": "png"}
        )
    )
    try:
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.5, timeout=300))
        assert done["counts"]["done"] == 1, done["items"]
        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        if "x-text-removed" not in item.headers:
            pytest.skip("this engine does not keep x-text-* on job items")
        cleaned = item.remove_text()
        assert cleaned.removed >= 1
        assert cleaned.removed == int(done["items"][0]["headers"]["x-text-removed"])
        assert cleaned.kept == int(done["items"][0]["headers"]["x-text-kept"])
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


def test_vectorize_job_item_has_the_paths(live: Live) -> None:
    """Newer engines keep the tools' own headers on job items. No model needed."""
    job = live.run(lambda c: c.jobs.create("vectorize", images=[BOXED], params={"mode": "mono"}))
    try:
        assert job["params"] == "mode=mono"
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.2, timeout=120))
        assert done["counts"]["done"] == 1, done["items"]
        assert done["items"][0]["content_type"] == "image/svg+xml"
        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        assert item.is_image
        assert item.content.startswith(b"<svg ")
        if "x-paths" not in item.headers:
            pytest.skip("this engine does not keep x-paths on job items")
        traced = item.vectorize()
        assert traced.paths == 1 == int(done["items"][0]["headers"]["x-paths"])
        assert (traced.width, traced.height) == (100, 80)
        with pytest.raises(PhotosError, match="x-faces"):
            item.blur_faces()
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


def test_job_with_urls_json_results_and_a_webhook(live: Live, server: LocalServer) -> None:
    # The local engine may fetch from and deliver to 127.0.0.1 (production may not).
    server.replies = [Reply(200, {"Content-Type": "image/png"}, PNG)]
    job = live.run(
        lambda c: c.jobs.create(
            "barcodes",
            urls=[server.url + "/in.png"],
            params={"all_formats": True},
            webhook_url=server.url + "/hook",
        )
    )
    try:
        assert job["params"] == "all_formats=true"
        done = live.run(lambda c: c.jobs.wait(job["id"], poll_interval=0.2, timeout=120))
        assert done["counts"]["done"] == 1, done["items"]

        item = live.run(lambda c: c.jobs.item(job["id"], 0))
        assert item.is_json
        assert not item.is_image
        assert item.json()["barcodes"] == []

        fetch, hook = server.wait_for(2)
        assert (fetch.method, fetch.path) == ("GET", "/in.png")
        assert (hook.method, hook.path) == ("POST", "/hook")
        secret = live.run(lambda c: c.webhook_secret())["secret"]
        event = webhooks.verify(hook.body, hook.headers["photos-signature"], secret)
        assert event["type"] == "job.completed"
        assert event["job"]["id"] == job["id"]
        assert event["job"]["status"] == "completed"
        with pytest.raises(webhooks.WebhookVerificationError):
            webhooks.verify(hook.body + b" ", hook.headers["photos-signature"], secret)
    finally:
        live.run(lambda c: c.jobs.delete(job["id"]))


# --- model work: once each, on small images -------------------------------------------


def test_read_text_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.read_text(DATA / "label.png")
    assert result["lines"], result
    line = result["lines"][0]
    assert line["text"]
    assert 0 <= line["score"] <= 1
    assert len(line["box"]) == 4


def test_erase_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.erase(PNG, rect=[(8, 8, 16, 12), "40,20,8,8"], format="png")
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (64, 48) == png_size(result.content)


async def test_read_label_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.read_label([DATA / "label.png", DATA / "caption.png"])
    assert isinstance(result["label"], dict)
    assert isinstance(result["barcodes"], list)
    assert any("250" in line for line in result["text"]), result["text"]


async def test_remove_text_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.remove_text(DATA / "caption.png", region="all", format="png")
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (307, 129)
    assert result.removed >= 1
    assert result.kept >= 0


def test_remove_background_staged_sync() -> None:
    # A canvas, with another image behind the subject (the `background` part).
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.remove_background(
            PNG, width=128, height=96, fill=0.8, background_image=BOXED, format="png"
        )
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (128, 96) == png_size(result.content)
    assert result.subject_found in (None, False)  # only ever said when there is none


async def test_crop_around_a_face_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.crop(
            PORTRAIT, aspect="1:1", width=256, height=256, focus="face", zoom=True, padding=0.5
        )
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height) == (256, 256)
    assert result.subject_found is True


def test_find_faces_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.find_faces(PORTRAIT)
        none = photos.find_faces(BOXED)
    assert (result["width"], result["height"]) == (512, 512)
    (face,) = result["faces"]
    assert face["score"] > 0.9
    assert set(face["box"]) == {"x", "y", "width", "height"}
    assert set(face["landmarks"]) == {"right_eye", "left_eye", "nose", "mouth_right", "mouth_left"}
    assert len(face["landmarks"]["nose"]) == 2
    assert face["landmarks"]["right_eye"][0] < face["landmarks"]["left_eye"][0]  # the person's own
    assert abs(face["roll"]) < 10
    assert none["faces"] == []


async def test_blur_faces_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.blur_faces(PORTRAIT, mode="pixelate", format="png")
        none = await photos.blur_faces(BOXED)
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (512, 512) == png_size(result.content)
    assert result.faces == 1
    assert none.faces == 0


def test_id_photo_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.id_photo(
            PORTRAIT, width_mm=35, height_mm=45, head_min_mm=32, head_max_mm=36
        )
        with pytest.raises(UnprocessableError):  # no face in it
            photos.id_photo(BOXED, document="us-passport")
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height) == (413, 531)  # 35 x 45 mm at 300 dpi
    assert result.head_mm is not None
    assert 32 <= result.head_mm <= 36
    # The portrait is small: the head had to be enlarged, and the tool says so.
    assert "low_resolution" in result.findings
    assert result.passed is False


async def test_denoise_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.denoise(PNG, strength=50, format="png")
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (64, 48) == png_size(result.content)


def test_colorize_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.colorize(PNG, strength=80, format="png")
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (64, 48) == png_size(result.content)


async def test_select_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.select(PORTRAIT, point=(220, 120))  # the cheek
        with pytest.raises(BadRequestError):  # outside the photo
            await photos.select(PORTRAIT, point=(900, 5))
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (512, 512) == png_size(result.content)
    assert result.score is not None
    assert 0.5 < result.score <= 1


def test_restore_faces_sync() -> None:
    with Photos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = photos.restore_faces(PORTRAIT, strength=80)
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height) == (512, 512)
    assert result.faces + result.faces_skipped == 1


async def test_caption_async() -> None:
    async with AsyncPhotos(API_KEY, base_url=BASE_URL, **OPTIONS) as photos:
        result = await photos.caption(PORTRAIT)
    assert result["caption"].strip()
    assert result["detail"] == "short"
    assert (result["width"], result["height"]) == (512, 512)
