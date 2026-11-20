"""The request each method makes, and how its result is read. Every test runs
against both clients."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest
from conftest import PNG, Harness, image_response, json_response, parts_of

from photos_sh import (
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

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><path d="M0 0z"/></svg>'


def query(request: httpx.Request) -> list[tuple[str, str]]:
    return list(request.url.params.multi_items())


def parts(request: httpx.Request) -> list[tuple[str, Optional[str], bytes]]:
    return [(p.name, p.filename, p.content) for p in parts_of(request)]


def svg_response(headers: Optional[dict[str, str]] = None) -> httpx.Response:
    base = {"content-type": "image/svg+xml", "x-image-width": "100", "x-image-height": "80"}
    return httpx.Response(200, content=SVG, headers={**base, **(headers or {})})


def assert_post(request: httpx.Request, path: str) -> None:
    assert request.method == "POST"
    assert request.url.path == "/api" + path
    assert request.headers["authorization"] == "Bearer test-key"


def assert_one_image(request: httpx.Request, filename: str = "image") -> None:
    parts = parts_of(request)
    assert [(p.name, p.filename, p.content) for p in parts] == [("image", filename, PNG)]


# --- image arguments ------------------------------------------------------------------


def test_image_from_bytes(api: Harness) -> None:
    api.run(lambda c: c.resize(PNG, width=10), image_response())
    assert_one_image(api.request)


def test_image_from_path(api: Harness, tmp_path: Path) -> None:
    path = tmp_path / "shoe.png"
    path.write_bytes(PNG)
    api.run(lambda c: c.resize(path, width=10), image_response())
    assert_one_image(api.request, "shoe.png")


def test_image_from_str_path(api: Harness, tmp_path: Path) -> None:
    path = tmp_path / "shoe.png"
    path.write_bytes(PNG)
    api.run(lambda c: c.resize(str(path), width=10), image_response())
    assert_one_image(api.request, "shoe.png")


def test_image_from_file_object(api: Harness, tmp_path: Path) -> None:
    path = tmp_path / "boot.png"
    path.write_bytes(PNG)
    with open(path, "rb") as f:
        api.run(lambda c: c.resize(f, width=10), image_response())
    assert_one_image(api.request, "boot.png")


def test_image_from_unnamed_stream(api: Harness) -> None:
    api.run(lambda c: c.resize(io.BytesIO(PNG), width=10), image_response())
    assert_one_image(api.request)


def test_image_of_a_wrong_type(api: Harness) -> None:
    with pytest.raises(TypeError, match="path"):
        api.run(lambda c: c.resize(123), image_response())
    with pytest.raises(TypeError, match="binary"):
        api.run(lambda c: c.resize(io.StringIO("text")), image_response())
    assert api.requests == []


# --- edit -----------------------------------------------------------------------------


def test_remove_background(api: Harness) -> None:
    result = api.run(
        lambda c: c.remove_background(
            PNG,
            format="jpg",
            quality=85,
            background="#ffffff",
            crop=True,
            padding=20,
            mask=False,
        ),
        image_response(
            {
                "content-type": "image/jpeg",
                "x-image-quality": "85",
                "server-timing": "decode;dur=3, model;dur=420",
            }
        ),
    )
    assert_post(api.request, "/v1/remove-background")
    assert query(api.request) == [
        ("format", "jpg"),
        ("quality", "85"),
        ("background", "#ffffff"),
        ("crop", "true"),
        ("padding", "20"),
        ("mask", "false"),
    ]
    assert_one_image(api.request)
    assert type(result) is RemoveBackgroundResult
    assert result.content == PNG
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height, result.quality) == (64, 48, 85)
    assert result.server_timing == "decode;dur=3, model;dur=420"
    assert result.subject_found is None  # the API did not say


def test_options_left_out_are_not_sent(api: Harness) -> None:
    result = api.run(lambda c: c.remove_background(PNG), image_response())
    assert api.request.url.query == b""
    assert result.quality is None
    assert result.server_timing is None


def test_remove_background_staged(api: Harness) -> None:
    result = api.run(
        lambda c: c.remove_background(
            PNG,
            format="jpg",
            background="white",
            width=800,
            height=600,
            fill=0.8,
            align="bottom",
            shadow="contact",
            reflection=True,
        ),
        image_response({"x-subject-found": "false"}),
    )
    assert_post(api.request, "/v1/remove-background")
    assert query(api.request) == [
        ("format", "jpg"),
        ("background", "white"),
        ("width", "800"),
        ("height", "600"),
        ("fill", "0.8"),
        ("align", "bottom"),
        ("shadow", "contact"),
        ("reflection", "true"),
    ]
    assert_one_image(api.request)
    assert result.subject_found is False  # no subject was found


def test_remove_background_of_a_studio_shot(api: Harness) -> None:
    api.run(lambda c: c.remove_background(PNG, studio=True, crop=True), image_response())
    assert_post(api.request, "/v1/remove-background")
    assert query(api.request) == [("crop", "true"), ("studio", "true")]
    assert_one_image(api.request)

    api.requests.clear()
    api.run(lambda c: c.remove_background(PNG, studio=None), image_response())
    assert api.request.url.query == b""  # not sent unless given


def test_remove_background_with_a_model(api: Harness) -> None:
    api.run(
        lambda c: c.remove_background(PNG, crop=True, model="lumen", studio=True), image_response()
    )
    assert_post(api.request, "/v1/remove-background")
    assert query(api.request) == [("crop", "true"), ("model", "lumen"), ("studio", "true")]
    assert_one_image(api.request)

    api.requests.clear()
    api.run(lambda c: c.remove_background(PNG, model="atlas"), image_response())
    assert query(api.request) == [("model", "atlas")]  # sent when given, even the default

    api.requests.clear()
    api.run(lambda c: c.remove_background(PNG, model="nova"), image_response())
    assert query(api.request) == [("model", "nova")]  # a model the API adds later

    api.requests.clear()
    api.run(lambda c: c.remove_background(PNG, model=None), image_response())
    assert api.request.url.query == b""  # not sent unless given, so the API's default applies


def test_remove_background_with_a_background_image(api: Harness, tmp_path: Path) -> None:
    api.run(
        lambda c: c.remove_background(PNG, shadow="drop", background_image=b"beach"),
        image_response(),
    )
    assert_post(api.request, "/v1/remove-background")
    assert query(api.request) == [("shadow", "drop")]  # the image is a part, not an option
    assert parts(api.request) == [("image", "image", PNG), ("background", "background", b"beach")]

    api.requests.clear()
    path = tmp_path / "beach.jpg"
    path.write_bytes(b"beach")
    api.run(lambda c: c.remove_background(PNG, background_image=path), image_response())
    assert parts(api.request) == [("image", "image", PNG), ("background", "beach.jpg", b"beach")]


def test_remove_background_with_its_own_background_blurred(api: Harness) -> None:
    api.run(lambda c: c.remove_background(PNG, blur=12.5), image_response())
    assert query(api.request) == [("blur", "12.5")]
    assert_one_image(api.request)


@pytest.mark.parametrize(
    ("headers", "found"),
    [
        ({"x-subject-found": "true"}, True),
        ({"x-subject-found": "false"}, False),
        ({"X-Subject-Found": " False "}, False),
        ({}, None),  # absent is unknown, not false
        ({"x-subject-found": ""}, None),
        ({"x-subject-found": "maybe"}, None),
    ],
)
def test_subject_found(api: Harness, headers: dict[str, str], found: Optional[bool]) -> None:
    cutout = api.run(lambda c: c.remove_background(PNG), image_response(headers))
    cropped = api.run(lambda c: c.crop(PNG, aspect="1:1"), image_response(headers))
    assert cutout.subject_found is found
    assert cropped.subject_found is found


def test_resize(api: Harness) -> None:
    api.run(
        lambda c: c.resize(
            PNG,
            width=800,
            height=600,
            fit="cover",
            enlarge=True,
            format="webp",
            quality=80,
            max_bytes=300000,
            background="white",
        ),
        image_response(),
    )
    assert_post(api.request, "/v1/resize")
    assert query(api.request) == [
        ("width", "800"),
        ("height", "600"),
        ("fit", "cover"),
        ("enlarge", "true"),
        ("format", "webp"),
        ("quality", "80"),
        ("max_bytes", "300000"),
        ("background", "white"),
    ]


def test_resize_trim_and_dpi(api: Harness) -> None:
    result = api.run(
        lambda c: c.resize(PNG, format="jpg", trim=True, trim_tolerance=25, dpi=300),
        image_response(),
    )
    assert_post(api.request, "/v1/resize")
    assert query(api.request) == [
        ("format", "jpg"),
        ("trim", "true"),
        ("trim_tolerance", "25"),
        ("dpi", "300"),
    ]
    assert_one_image(api.request)
    assert type(result) is ImageResult


def test_upscale(api: Harness) -> None:
    api.run(lambda c: c.upscale(PNG, scale=2.5, format="png", quality=90), image_response())
    assert_post(api.request, "/v1/upscale")
    assert query(api.request) == [("scale", "2.5"), ("format", "png"), ("quality", "90")]


def test_erase_with_rects_and_mask(api: Harness) -> None:
    mask = b"mask-bytes"
    api.run(
        lambda c: c.erase(PNG, rect=[(1, 2, 30, 40), "5,6,7,8"], mask=mask, format="jpg"),
        image_response(),
    )
    assert_post(api.request, "/v1/erase")
    assert api.request.url.query == b"rect=1%2C2%2C30%2C40&rect=5%2C6%2C7%2C8&format=jpg"
    assert query(api.request) == [("rect", "1,2,30,40"), ("rect", "5,6,7,8"), ("format", "jpg")]
    assert [(p.name, p.filename, p.content) for p in parts_of(api.request)] == [
        ("image", "image", PNG),
        ("mask", "mask", mask),
    ]


def test_erase_with_one_rect(api: Harness) -> None:
    api.run(lambda c: c.erase(PNG, rect=(1, 2, 30, 40)), image_response())
    assert query(api.request) == [("rect", "1,2,30,40")]


def test_erase_needs_an_area(api: Harness) -> None:
    with pytest.raises(ValueError, match="rect and/or mask"):
        api.run(lambda c: c.erase(PNG), image_response())
    with pytest.raises(ValueError, match="x, y, width, height"):
        api.run(lambda c: c.erase(PNG, rect=[(1, 2, 3)]), image_response())
    assert api.requests == []


def test_remove_text(api: Harness) -> None:
    result = api.run(
        lambda c: c.remove_text(PNG, region="all", matching=r"sale|€", format="png", quality=90),
        image_response({"x-text-removed": "3", "x-text-kept": "1"}),
    )
    assert_post(api.request, "/v1/remove-text")
    assert query(api.request) == [
        ("region", "all"),
        ("matching", "sale|€"),
        ("format", "png"),
        ("quality", "90"),
    ]
    assert isinstance(result, RemoveTextResult)
    assert (result.removed, result.kept) == (3, 1)
    assert (result.width, result.height) == (64, 48)


def test_run_with_a_preset(api: Harness) -> None:
    api.run(lambda c: c.run(PNG, preset="marketplace"), image_response())
    assert_post(api.request, "/v1/run")
    assert query(api.request) == [("preset", "marketplace")]
    assert_one_image(api.request)


def test_run_with_a_recipe(api: Harness) -> None:
    recipe = '[resize]\nwidth = 100\n# "ž"\n'
    api.run(lambda c: c.run(PNG, recipe=recipe), image_response())
    assert api.request.url.query == b""
    parts = {p.name: p for p in parts_of(api.request)}
    assert set(parts) == {"image", "recipe"}
    assert parts["recipe"].filename == "recipe.toml"
    assert parts["recipe"].content.decode() == recipe
    assert parts["image"].content == PNG


def test_run_needs_exactly_one_of_preset_and_recipe(api: Harness) -> None:
    with pytest.raises(ValueError, match="preset"):
        api.run(lambda c: c.run(PNG), image_response())
    with pytest.raises(ValueError, match="preset"):
        api.run(lambda c: c.run(PNG, preset="web", recipe="x"), image_response())
    assert api.requests == []


# What a recipe's reading steps read, as the engine sends it: JSON, non-ASCII escaped.
BARCODES = '[{"format":"EAN-13","value":"3850104010017","gs1":"3850104010017"},' + (
    '{"format":"QR","value":"https://photos.sh","gs1":null}]'
)
TEXT = '["Pr\\u0161ut","500 g","\\ud83d\\ude00"]'


def test_run_with_reading_steps(api: Harness) -> None:
    recipe = "[barcodes]\nall_formats = true\n\n[text]\n"
    result = api.run(
        lambda c: c.run(PNG, recipe=recipe),
        image_response({"X-Barcodes": BARCODES, "X-Text": TEXT, "X-Text-Truncated": "true"}),
    )
    assert isinstance(result, ImageResult)
    assert result.content == PNG
    assert result.barcodes == [
        {"format": "EAN-13", "value": "3850104010017", "gs1": "3850104010017"},
        {"format": "QR", "value": "https://photos.sh", "gs1": None},
    ]
    assert result.text == ["Pršut", "500 g", "\U0001f600"]
    assert result.text_truncated is True


def test_run_without_reading_steps(api: Harness) -> None:
    result = api.run(lambda c: c.run(PNG, preset="marketplace"), image_response())
    assert result.barcodes is None  # the step was not in the recipe
    assert result.text is None
    assert result.text_truncated is False


def test_run_with_reading_steps_that_found_nothing(api: Harness) -> None:
    result = api.run(
        lambda c: c.run(PNG, recipe="[barcodes]\n[text]\n"),
        image_response({"x-barcodes": "[]", "x-text": "[]"}),
    )
    assert result.barcodes == []
    assert result.text == []
    assert result.text_truncated is False


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not json",
        "[",
        '{"barcodes": []}',
        '"EAN-13"',
        "[1, 2]",
        '[{"format": "EAN-13"}]',
        '[{"format": "EAN-13", "value": 385}]',
        '[{"format": "EAN-13", "value": "385", "gs1": 385}]',
    ],
)
def test_unreadable_barcodes_header_is_taken_as_absent(api: Harness, value: str) -> None:
    result = api.run(lambda c: c.run(PNG, preset="web"), image_response({"x-barcodes": value}))
    assert result.barcodes is None


@pytest.mark.parametrize("value", ["", "not json", '"Pr\\u0161ut"', '{"lines": []}', '["a", 1]'])
def test_unreadable_text_header_is_taken_as_absent(api: Harness, value: str) -> None:
    result = api.run(lambda c: c.run(PNG, preset="web"), image_response({"x-text": value}))
    assert result.text is None


@pytest.mark.parametrize(("value", "truncated"), [("true", True), ("false", False), ("x", False)])
def test_text_truncated(api: Harness, value: str, truncated: bool) -> None:
    result = api.run(
        lambda c: c.run(PNG, preset="web"),
        image_response({"x-text": "[]", "x-text-truncated": value}),
    )
    assert result.text_truncated is truncated


def test_enhance(api: Harness) -> None:
    result = api.run(
        lambda c: c.enhance(
            PNG,
            auto=True,
            levels=False,
            white_balance=True,
            brightness=10,
            contrast=-20.5,
            saturation=-100,
            temperature=15,
            sharpen=40,
            format="webp",
            quality=80,
        ),
        image_response(),
    )
    assert_post(api.request, "/v1/enhance")
    assert query(api.request) == [
        ("auto", "true"),
        ("levels", "false"),
        ("white_balance", "true"),
        ("brightness", "10"),
        ("contrast", "-20.5"),
        ("saturation", "-100"),
        ("temperature", "15"),
        ("sharpen", "40"),
        ("format", "webp"),
        ("quality", "80"),
    ]
    assert_one_image(api.request)
    assert type(result) is ImageResult
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_enhance_without_settings(api: Harness) -> None:
    api.run(lambda c: c.enhance(PNG), image_response())
    assert_post(api.request, "/v1/enhance")
    assert api.request.url.query == b""


def test_crop(api: Harness) -> None:
    result = api.run(
        lambda c: c.crop(
            PNG,
            aspect="4:5",
            width=400,
            height=500,
            zoom=True,
            padding=0.6,
            focus="face",
            format="jpg",
            quality=85,
        ),
        image_response({"x-subject-found": "true"}),
    )
    assert_post(api.request, "/v1/crop")
    assert api.request.url.query.startswith(b"aspect=4%3A5&width=400")
    assert query(api.request) == [
        ("aspect", "4:5"),
        ("width", "400"),
        ("height", "500"),
        ("zoom", "true"),
        ("padding", "0.6"),
        ("focus", "face"),
        ("format", "jpg"),
        ("quality", "85"),
    ]
    assert_one_image(api.request)
    assert type(result) is CropResult
    assert result.subject_found is True
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_crop_with_the_shape_as_a_number(api: Harness) -> None:
    api.run(lambda c: c.crop(PNG, aspect=1.5), image_response())
    assert query(api.request) == [("aspect", "1.5")]


def test_watermark_with_text(api: Harness) -> None:
    result = api.run(
        lambda c: c.watermark(
            PNG,
            text="© Acme & Co",
            color="#000000",
            position="top-left",
            scale=30,
            opacity=62.5,
            margin=0,
            tile=False,
            format="jpg",
            quality=90,
        ),
        image_response(),
    )
    assert_post(api.request, "/v1/watermark")
    assert query(api.request) == [
        ("text", "© Acme & Co"),
        ("color", "#000000"),
        ("position", "top-left"),
        ("scale", "30"),
        ("opacity", "62.5"),
        ("margin", "0"),
        ("tile", "false"),
        ("format", "jpg"),
        ("quality", "90"),
    ]
    assert_one_image(api.request)
    assert type(result) is ImageResult


def test_watermark_with_an_image(api: Harness, tmp_path: Path) -> None:
    api.run(lambda c: c.watermark(PNG, watermark=b"logo", tile=True), image_response())
    assert_post(api.request, "/v1/watermark")
    assert query(api.request) == [("tile", "true")]
    assert parts(api.request) == [("image", "image", PNG), ("watermark", "watermark", b"logo")]

    api.requests.clear()
    path = tmp_path / "logo.png"
    path.write_bytes(b"logo")
    api.run(lambda c: c.watermark(PNG, watermark=path), image_response())
    assert api.request.url.query == b""
    assert parts(api.request) == [("image", "image", PNG), ("watermark", "logo.png", b"logo")]


def test_watermark_needs_exactly_one_of_text_and_image(api: Harness) -> None:
    with pytest.raises(ValueError, match="text or a watermark image"):
        api.run(lambda c: c.watermark(PNG), image_response())
    with pytest.raises(ValueError, match="text or a watermark image"):
        api.run(lambda c: c.watermark(PNG, text="a", watermark=b"logo"), image_response())
    assert api.requests == []


def test_expand_to_a_shape(api: Harness) -> None:
    result = api.run(
        lambda c: c.expand(PNG, aspect="16:9", fill="#ffffff", format="png", quality=90),
        image_response(),
    )
    assert_post(api.request, "/v1/expand")
    assert query(api.request) == [
        ("aspect", "16:9"),
        ("fill", "#ffffff"),
        ("format", "png"),
        ("quality", "90"),
    ]
    assert_one_image(api.request)
    assert type(result) is ImageResult


def test_expand_by_pixels(api: Harness) -> None:
    api.run(lambda c: c.expand(PNG, left=10, right=0, top=20, bottom=5), image_response())
    assert query(api.request) == [("left", "10"), ("right", "0"), ("top", "20"), ("bottom", "5")]


def test_vectorize(api: Harness, tmp_path: Path) -> None:
    result = api.run(
        lambda c: c.vectorize(PNG, mode="mono", curves="polygon", detail=6, speckle=8),
        svg_response({"x-paths": "23"}),
    )
    assert_post(api.request, "/v1/vectorize")
    assert query(api.request) == [
        ("mode", "mono"),
        ("curves", "polygon"),
        ("detail", "6"),
        ("speckle", "8"),
    ]
    assert_one_image(api.request)
    assert type(result) is VectorizeResult
    assert result.paths == 23
    assert result.content == SVG
    assert result.content_type == "image/svg+xml"
    assert (result.width, result.height) == (100, 80)  # the size it was traced at
    assert (result.quality, result.server_timing) == (None, None)
    result.save(tmp_path / "logo.svg")
    assert (tmp_path / "logo.svg").read_bytes() == SVG


def test_vectorize_without_the_paths_header(api: Harness) -> None:
    result = api.run(lambda c: c.vectorize(PNG), svg_response())
    assert api.request.url.query == b""
    assert result.paths == 0


def test_blur_faces(api: Harness) -> None:
    result = api.run(
        lambda c: c.blur_faces(
            PNG,
            mode="fill",
            strength=80,
            padding=0.3,
            color="black",
            min_score=0.4,
            format="jpg",
            quality=85,
        ),
        image_response({"x-faces": "3"}),
    )
    assert_post(api.request, "/v1/blur-faces")
    assert query(api.request) == [
        ("mode", "fill"),
        ("strength", "80"),
        ("padding", "0.3"),
        ("color", "black"),
        ("min_score", "0.4"),
        ("format", "jpg"),
        ("quality", "85"),
    ]
    assert_one_image(api.request)
    assert type(result) is BlurFacesResult
    assert result.faces == 3
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_blur_faces_without_the_header(api: Harness) -> None:
    result = api.run(lambda c: c.blur_faces(PNG), image_response())
    assert api.request.url.query == b""
    assert result.faces == 0


def test_id_photo_for_a_document(api: Harness) -> None:
    result = api.run(
        lambda c: c.id_photo(
            PNG, document="us-passport", dpi=600, background="document", format="png", quality=95
        ),
        image_response(
            {
                "x-id-photo-passed": "false",
                "x-id-photo-findings": "low_resolution,background_not_plain",
                "x-id-photo-head-mm": "30.0",
            }
        ),
    )
    assert_post(api.request, "/v1/id-photo")
    assert query(api.request) == [
        ("document", "us-passport"),
        ("dpi", "600"),
        ("background", "document"),
        ("format", "png"),
        ("quality", "95"),
    ]
    assert_one_image(api.request)
    assert type(result) is IdPhotoResult
    assert result.passed is False
    assert result.findings == ["low_resolution", "background_not_plain"]
    assert result.head_mm == 30.0
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_id_photo_by_its_sizes(api: Harness) -> None:
    result = api.run(
        lambda c: c.id_photo(
            PNG,
            width_mm=35,
            height_mm=45,
            head_min_mm=32,
            head_max_mm=36,
            eyes_min_mm=28.5,
            eyes_max_mm=35,
        ),
        image_response(
            {
                "x-id-photo-passed": "true",
                "x-id-photo-findings": "",  # nothing was found
                "x-id-photo-head-mm": "34.2",
            }
        ),
    )
    assert query(api.request) == [
        ("width_mm", "35"),
        ("height_mm", "45"),
        ("head_min_mm", "32"),
        ("head_max_mm", "36"),
        ("eyes_min_mm", "28.5"),
        ("eyes_max_mm", "35"),
    ]
    assert result.passed is True
    assert result.findings == []
    assert result.head_mm == 34.2


@pytest.mark.parametrize("head_mm", [None, "", "tall", "nan"])
def test_id_photo_without_the_headers(api: Harness, head_mm: Optional[str]) -> None:
    headers = {} if head_mm is None else {"x-id-photo-head-mm": head_mm}
    result = api.run(lambda c: c.id_photo(PNG, document="uk-passport"), image_response(headers))
    assert result.passed is False
    assert result.findings == []
    assert result.head_mm is None


@pytest.mark.parametrize(
    ("method", "path"), [("denoise", "/v1/denoise"), ("colorize", "/v1/colorize")]
)
def test_denoise_and_colorize(api: Harness, method: str, path: str) -> None:
    result = api.run(
        lambda c: getattr(c, method)(PNG, strength=50, format="jpg", quality=90), image_response()
    )
    assert_post(api.request, path)
    assert query(api.request) == [("strength", "50"), ("format", "jpg"), ("quality", "90")]
    assert_one_image(api.request)
    assert type(result) is ImageResult
    assert (result.content, result.width, result.height) == (PNG, 64, 48)

    api.requests.clear()
    api.run(lambda c: getattr(c, method)(PNG), image_response())
    assert api.request.url.query == b""


def test_select(api: Harness) -> None:
    result = api.run(
        lambda c: c.select(
            PNG,
            point=[(120, 80), "200.5,90"],
            exclude=[(10, 10), (300, 20.5)],
            box=(40, 30, 400, 300),
            pick="largest",
            mask=False,
            crop=True,
            padding=12,
            background="white",
            format="jpg",
            quality=85,
        ),
        image_response({"x-select-score": "0.931"}),
    )
    assert_post(api.request, "/v1/select")
    assert api.request.url.query.startswith(
        b"point=120%2C80&point=200.5%2C90&exclude=10%2C10&exclude=300%2C20.5&box=40%2C30%2C400%2C300"
    )
    assert query(api.request) == [
        ("point", "120,80"),
        ("point", "200.5,90"),
        ("exclude", "10,10"),
        ("exclude", "300,20.5"),
        ("box", "40,30,400,300"),
        ("pick", "largest"),
        ("mask", "false"),
        ("crop", "true"),
        ("padding", "12"),
        ("background", "white"),
        ("format", "jpg"),
        ("quality", "85"),
    ]
    assert_one_image(api.request)
    assert type(result) is SelectResult
    assert result.score == 0.931
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_select_with_one_point(api: Harness) -> None:
    api.run(lambda c: c.select(PNG, point=(120, 80), exclude=(5, 6)), image_response())
    assert query(api.request) == [("point", "120,80"), ("exclude", "5,6")]
    api.requests.clear()
    api.run(lambda c: c.select(PNG, point="120,80"), image_response())
    assert query(api.request) == [("point", "120,80")]


def test_select_with_a_box(api: Harness) -> None:
    api.run(lambda c: c.select(PNG, box="40,30,400,300", mask=True), image_response())
    assert query(api.request) == [("box", "40,30,400,300"), ("mask", "true")]


@pytest.mark.parametrize("score", [None, "", "high", "inf"])
def test_select_without_the_score(api: Harness, score: Optional[str]) -> None:
    headers = {} if score is None else {"x-select-score": score}
    result = api.run(lambda c: c.select(PNG, point=(1, 2)), image_response(headers))
    assert result.score is None


def test_select_needs_a_point_or_a_box(api: Harness) -> None:
    with pytest.raises(ValueError, match="point and/or box"):
        api.run(lambda c: c.select(PNG), image_response())
    with pytest.raises(ValueError, match="point and/or box"):
        api.run(lambda c: c.select(PNG, exclude=(5, 5)), image_response())
    with pytest.raises(ValueError, match=r"a point is \(x, y\)"):
        api.run(lambda c: c.select(PNG, point=[(1, 2, 3)]), image_response())
    with pytest.raises(ValueError, match=r"a point is \(x, y\)"):
        api.run(lambda c: c.select(PNG, point=(1, 2), exclude=[(1,)]), image_response())
    with pytest.raises(ValueError, match="one box"):
        api.run(lambda c: c.select(PNG, box=[(1, 2, 3, 4), (5, 6, 7, 8)]), image_response())
    assert api.requests == []


def test_restore_faces(api: Harness) -> None:
    result = api.run(
        lambda c: c.restore_faces(PNG, strength=70, min_score=0.5, format="png", quality=90),
        image_response({"x-faces": "2", "x-faces-skipped": "1"}),
    )
    assert_post(api.request, "/v1/restore-faces")
    assert query(api.request) == [
        ("strength", "70"),
        ("min_score", "0.5"),
        ("format", "png"),
        ("quality", "90"),
    ]
    assert_one_image(api.request)
    assert type(result) is RestoreFacesResult
    assert (result.faces, result.faces_skipped) == (2, 1)
    assert (result.content, result.width, result.height) == (PNG, 64, 48)


def test_restore_faces_without_the_headers(api: Harness) -> None:
    result = api.run(lambda c: c.restore_faces(PNG), image_response())
    assert api.request.url.query == b""
    assert (result.faces, result.faces_skipped) == (0, 0)


# --- check and fix --------------------------------------------------------------------


def test_fix(api: Harness) -> None:
    result = api.run(
        lambda c: c.fix(PNG, "amazon"),
        image_response(
            {"x-marketplace-passed": "false", "x-marketplace-findings": "too_small,blurry"}
        ),
    )
    assert_post(api.request, "/v1/fix")
    assert query(api.request) == [("marketplace", "amazon")]
    assert isinstance(result, FixResult)
    assert result.passed is False
    assert result.findings == ["too_small", "blurry"]


def test_fix_that_passes(api: Harness) -> None:
    passed = api.run(
        lambda c: c.fix(PNG, marketplace="ebay"),
        image_response({"x-marketplace-passed": "true", "x-marketplace-findings": ""}),
    )
    assert passed.passed is True
    assert passed.findings == []
    without_header = api.run(
        lambda c: c.fix(PNG, "ebay"), image_response({"x-marketplace-passed": "true"})
    )
    assert without_header.findings == []


def test_check(api: Harness) -> None:
    body = {
        "metrics": {"width": 64, "height": 48, "sharpness": 0.7},
        "findings": [{"code": "too_small", "severity": "error", "message": "small"}],
        "marketplace": {
            "marketplace": "amazon",
            "passed": False,
            "findings": [],
            "not_checked": [],
        },
        "added_later": 1,
    }
    result = api.run(
        lambda c: c.check(PNG, marketplace="amazon", subject=True, text=False),
        json_response(body),
    )
    assert_post(api.request, "/v1/check")
    assert query(api.request) == [
        ("marketplace", "amazon"),
        ("subject", "true"),
        ("text", "false"),
    ]
    assert_one_image(api.request)
    assert result == body  # unknown fields are kept


# --- read -----------------------------------------------------------------------------


def test_read_barcodes(api: Harness) -> None:
    body = {
        "barcodes": [{"format": "EAN-13", "value": "4006381333931", "gs1": "4006381333931"}],
        "variant": "plain",
    }
    result = api.run(
        lambda c: c.read_barcodes(PNG, all_formats=True, engine="zbar"), json_response(body)
    )
    assert_post(api.request, "/v1/barcodes")
    assert query(api.request) == [("all_formats", "true"), ("engine", "zbar")]
    assert result["barcodes"][0]["value"] == "4006381333931"


def test_read_text(api: Harness) -> None:
    body = {"lines": [{"text": "SALE", "score": 0.99, "box": [[0, 0], [9, 0], [9, 9], [0, 9]]}]}
    result = api.run(lambda c: c.read_text(PNG), json_response(body))
    assert_post(api.request, "/v1/ocr")
    assert api.request.url.query == b""
    assert_one_image(api.request)
    assert result["lines"][0]["text"] == "SALE"


def test_read_label_with_several_images(api: Harness, tmp_path: Path) -> None:
    back = tmp_path / "back.png"
    back.write_bytes(b"back")
    body = {"label": {"gtin": "4006381333931"}, "barcodes": [], "text": ["a"]}
    result = api.run(lambda c: c.read_label([PNG, back]), json_response(body))
    assert_post(api.request, "/v1/label")
    assert [(p.name, p.filename, p.content) for p in parts_of(api.request)] == [
        ("image", "image", PNG),
        ("image", "back.png", b"back"),
    ]
    assert result["label"]["gtin"] == "4006381333931"


def test_read_label_with_one_image(api: Harness) -> None:
    api.run(lambda c: c.read_label(PNG), json_response({"label": {}, "barcodes": [], "text": []}))
    assert_one_image(api.request)


def test_identify(api: Harness) -> None:
    body = {
        "catalogue": "whisky",
        "candidates": [{"product_id": "7", "title": "T", "score": 0.9, "evidence": ["barcode"]}],
        "label": {},
        "barcodes": [],
    }
    result = api.run(
        lambda c: c.identify([PNG, PNG, PNG], catalogue="whisky", top=3), json_response(body)
    )
    assert_post(api.request, "/v1/identify")
    assert query(api.request) == [("catalogue", "whisky"), ("top", "3")]
    assert [p.name for p in parts_of(api.request)] == ["image"] * 3
    assert result["candidates"][0]["product_id"] == "7"


@pytest.mark.parametrize("count", [0, 9])
def test_too_few_or_too_many_images(api: Harness, count: int) -> None:
    with pytest.raises(ValueError, match="1 to 8"):
        api.run(lambda c: c.identify([PNG] * count), json_response({}))
    with pytest.raises(ValueError, match="1 to 8"):
        api.run(lambda c: c.read_label([PNG] * count), json_response({}))
    assert api.requests == []


def test_palette(api: Harness) -> None:
    body = {
        "width": 64,
        "height": 48,
        "colors": [
            {"hex": "#ffffff", "rgb": [255, 255, 255], "share": 0.9},
            {"hex": "#141ec8", "rgb": [20, 30, 200], "share": 0.1},
        ],
        "added_later": 1,
    }
    result = api.run(lambda c: c.palette(PNG, colors=2), json_response(body))
    assert_post(api.request, "/v1/palette")
    assert query(api.request) == [("colors", "2")]
    assert_one_image(api.request)
    assert result == body  # unknown fields are kept
    assert result["colors"][1]["hex"] == "#141ec8"
    assert result["colors"][1]["share"] == 0.1


def test_find_faces(api: Harness) -> None:
    face = {
        "box": {"x": 180.5, "y": 60.0, "width": 120.0, "height": 160.0},
        "landmarks": {
            "right_eye": [210.0, 120.0],
            "left_eye": [270.0, 121.0],
            "nose": [240.0, 150.0],
            "mouth_right": [215.0, 180.0],
            "mouth_left": [265.0, 181.0],
        },
        "score": 0.93,
        "roll": 0.9,
    }
    body = {"width": 512, "height": 512, "faces": [face]}
    result = api.run(lambda c: c.find_faces(PNG, min_score=0.5), json_response(body))
    assert_post(api.request, "/v1/faces")
    assert query(api.request) == [("min_score", "0.5")]
    assert_one_image(api.request)
    assert result == body
    assert result["faces"][0]["box"]["width"] == 120.0
    assert result["faces"][0]["landmarks"]["nose"] == [240.0, 150.0]


def test_find_faces_when_there_are_none(api: Harness) -> None:
    result = api.run(
        lambda c: c.find_faces(PNG), json_response({"width": 64, "height": 48, "faces": []})
    )
    assert api.request.url.query == b""
    assert result["faces"] == []


def test_caption(api: Harness) -> None:
    body = {
        "caption": "A woman in a space suit posing for a photo.",
        "detail": "detailed",
        "width": 512,
        "height": 512,
    }
    result = api.run(lambda c: c.caption(PNG, detail="detailed"), json_response(body))
    assert_post(api.request, "/v1/caption")
    assert query(api.request) == [("detail", "detailed")]
    assert_one_image(api.request)
    assert result == body
    assert result["caption"].startswith("A woman")

    api.requests.clear()
    api.run(lambda c: c.caption(PNG), json_response(body))
    assert api.request.url.query == b""


# --- account and service --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("account", "/v1/account", {"account": "acme", "credits": 120, "prices": {"resize": 1}}),
        ("presets", "/v1/presets", [{"name": "web", "description": "Web-ready"}]),
        ("marketplaces", "/v1/marketplaces", [{"name": "amazon", "title": "Amazon"}]),
        (
            "id_photos",
            "/v1/id-photos",
            [
                {
                    "name": "uk-passport",
                    "title": "United Kingdom passport",
                    "checked": "2026-11-12",
                    "sources": ["https://www.gov.uk/photos-for-passports"],
                    "notes": ["A neutral expression."],
                    "width_mm": 35.0,
                    "height_mm": 45.0,
                    "head_min_mm": 29.0,
                    "head_max_mm": 34.0,
                    "background": "#dcdcdc",
                    "alteration": "unaltered by computer software",
                }
            ],
        ),
        ("webhook_secret", "/v1/webhook-secret", {"secret": "whsec_1", "header": "Photos-Sig"}),
    ],
)
def test_get_endpoints(api: Harness, method: str, path: str, body: Any) -> None:
    result = api.run(lambda c: getattr(c, method)(), json_response(body))
    assert api.request.method == "GET"
    assert api.request.url.path == "/api" + path
    assert api.request.headers["authorization"] == "Bearer test-key"
    assert api.request.content == b""
    assert result == body


def test_preset(api: Harness) -> None:
    toml = '# Marketplace\n[resize]\nwidth = 2000\n# "Pršut"\n'
    response = httpx.Response(
        200,
        content=toml.encode(),
        headers={"content-type": "application/toml; charset=utf-8"},
    )
    result = api.run(lambda c: c.preset("marketplace"), response)
    assert api.request.method == "GET"
    assert api.request.url.path == "/api/v1/presets/marketplace"
    assert api.request.headers["authorization"] == "Bearer test-key"
    assert api.request.content == b""
    assert result == toml


def test_preset_names_are_escaped_in_the_path(api: Harness) -> None:
    api.run(lambda c: c.preset("a/b c?"), httpx.Response(200, text="[resize]\n"))
    assert api.request.url.raw_path == b"/api/v1/presets/a%2Fb%20c%3F"


def test_an_unknown_preset_is_not_found(api: Harness) -> None:
    from photos_sh import NotFoundError

    with pytest.raises(NotFoundError) as caught:
        api.run(
            lambda c: c.preset("nope"),
            json_response({"error": {"code": "not_found", "message": "no preset nope"}}, 404),
        )
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    assert caught.value.message == "no preset nope"


@pytest.mark.parametrize(("status", "state"), [(200, "ok"), (503, "loading"), (503, "failed")])
def test_health(api: Harness, status: int, state: str) -> None:
    result = api.run(lambda c: c.health(), json_response({"status": state}, status))
    assert api.request.method == "GET"
    assert api.request.url.path == "/api/health"
    assert result == state
    assert api.sleeps == []  # a 503 here is an answer, not something to retry


# --- jobs -----------------------------------------------------------------------------

JOB = {
    "id": "job_1",
    "operation": "resize",
    "params": "width=100",
    "status": "queued",
    "created_at": 1,
    "items": [{"input": "https://example.com/1.jpg", "status": "pending"}],
    "counts": {"total": 1, "done": 0, "failed": 0, "pending": 1},
}


def test_jobs_create_with_urls_sends_json(api: Harness) -> None:
    result = api.run(
        lambda c: c.jobs.create(
            "remove-background",
            urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
            params={"format": "png", "crop": True, "padding": 10, "model": "muse", "quality": None},
            webhook_url="https://example.com/hook",
        ),
        json_response(JOB, 202),
    )
    assert_post(api.request, "/v1/jobs")
    assert api.request.headers["content-type"] == "application/json"
    assert json.loads(api.request.content) == {
        "operation": "remove-background",
        "inputs": ["https://example.com/1.jpg", "https://example.com/2.jpg"],
        "params": {"format": "png", "crop": True, "padding": 10, "model": "muse"},
        "webhook_url": "https://example.com/hook",
    }
    assert result == JOB


def test_jobs_create_with_a_query_string_and_recipe(api: Harness) -> None:
    api.run(
        lambda c: c.jobs.create("run", urls=["https://example.com/1.jpg"], recipe="[resize]"),
        json_response(JOB, 202),
    )
    assert json.loads(api.request.content) == {
        "operation": "run",
        "inputs": ["https://example.com/1.jpg"],
        "recipe": "[resize]",
    }
    api.requests.clear()
    api.run(
        lambda c: c.jobs.create("run", urls=["https://example.com/1.jpg"], params="preset=web"),
        json_response(JOB, 202),
    )
    assert json.loads(api.request.content)["params"] == "preset=web"


def test_jobs_create_with_images_sends_multipart(api: Harness, tmp_path: Path) -> None:
    path = tmp_path / "b.png"
    path.write_bytes(b"second")
    api.run(
        lambda c: c.jobs.create(
            "resize",
            images=[PNG, path],
            urls=["https://example.com/3.jpg"],
            params={"width": 100, "enlarge": True, "background": "#fff"},
            recipe="r",
            webhook_url="https://example.com/hook",
        ),
        json_response(JOB, 202),
    )
    assert_post(api.request, "/v1/jobs")
    parts = parts_of(api.request)
    assert [(p.name, p.filename, p.content) for p in parts] == [
        ("operation", None, b"resize"),
        ("params", None, b"width=100&enlarge=true&background=%23fff"),
        ("webhook_url", None, b"https://example.com/hook"),
        ("url", None, b"https://example.com/3.jpg"),
        ("recipe", "recipe.toml", b"r"),
        ("image", "image-1", PNG),
        ("image", "b.png", b"second"),
    ]


@pytest.mark.parametrize(
    "operation",
    [
        "enhance",
        "crop",
        "palette",
        "watermark",
        "expand",
        "vectorize",
        "faces",
        "blur-faces",
        "id-photo",
        "denoise",
        "colorize",
        "select",
        "restore-faces",
        "caption",
    ],
)
def test_jobs_create_takes_the_newer_operations(api: Harness, operation: str) -> None:
    api.run(
        lambda c: c.jobs.create(operation, urls=["https://example.com/1.jpg"]),
        json_response({**JOB, "operation": operation}, 202),
    )
    assert json.loads(api.request.content) == {
        "operation": operation,
        "inputs": ["https://example.com/1.jpg"],
    }


def test_jobs_create_with_an_option_that_repeats(api: Harness) -> None:
    params = {"point": ["120,80", "200,90"], "exclude": ["10,10"], "crop": True, "pick": None}
    encoded = "point=120%2C80&point=200%2C90&exclude=10%2C10&crop=true"
    api.run(lambda c: c.jobs.create("select", images=[PNG], params=params), json_response(JOB, 202))
    assert parts(api.request) == [
        ("operation", None, b"select"),
        ("params", None, encoded.encode()),
        ("image", "image-1", PNG),
    ]

    # In JSON too it goes as a query string: the API does not read a list from an object.
    api.requests.clear()
    api.run(
        lambda c: c.jobs.create("select", urls=["https://example.com/1.jpg"], params=params),
        json_response(JOB, 202),
    )
    assert json.loads(api.request.content) == {
        "operation": "select",
        "inputs": ["https://example.com/1.jpg"],
        "params": encoded,
    }


def test_jobs_create_checks_its_inputs(api: Harness) -> None:
    with pytest.raises(ValueError, match="at least one"):
        api.run(lambda c: c.jobs.create("resize"), json_response(JOB, 202))
    with pytest.raises(TypeError, match="sequence of URLs"):
        api.run(lambda c: c.jobs.create("resize", urls="https://x"), json_response(JOB, 202))
    with pytest.raises(TypeError, match="sequence of images"):
        api.run(lambda c: c.jobs.create("resize", images=PNG), json_response(JOB, 202))
    assert api.requests == []


def test_jobs_get_list_delete(api: Harness) -> None:
    assert api.run(lambda c: c.jobs.get("job_1"), json_response(JOB)) == JOB
    assert (api.request.method, api.request.url.path) == ("GET", "/api/v1/jobs/job_1")
    api.requests.clear()

    summary = [{"id": "job_1", "operation": "resize", "status": "completed", "finished_at": None}]
    assert api.run(lambda c: c.jobs.list(), json_response(summary)) == summary
    assert (api.request.method, api.request.url.path) == ("GET", "/api/v1/jobs")
    api.requests.clear()

    assert api.run(lambda c: c.jobs.delete("job_1"), httpx.Response(204)) is None
    assert (api.request.method, api.request.url.path) == ("DELETE", "/api/v1/jobs/job_1")


def test_job_ids_are_escaped_in_the_path(api: Harness) -> None:
    api.run(lambda c: c.jobs.get("a/b c"), json_response(JOB))
    assert api.request.url.raw_path == b"/api/v1/jobs/a%2Fb%20c"


def test_jobs_item_as_an_image(api: Harness) -> None:
    result = api.run(lambda c: c.jobs.item("job_1", 2), image_response({"x-image-quality": "80"}))
    assert (api.request.method, api.request.url.path) == ("GET", "/api/v1/jobs/job_1/items/2")
    assert isinstance(result, JobItemResult)
    assert result.is_image
    assert not result.is_json
    assert result.content == PNG
    assert (result.width, result.height, result.quality) == (64, 48, 80)
    assert result.headers["X-Image-Width"] == "64"


def test_jobs_item_keeps_what_the_reading_steps_read(api: Harness) -> None:
    item = api.run(
        lambda c: c.jobs.item("job_1", 0),
        image_response({"X-Barcodes": BARCODES, "X-Text": TEXT, "X-Text-Truncated": "true"}),
    )
    assert item.barcodes is not None
    assert [code["value"] for code in item.barcodes] == ["3850104010017", "https://photos.sh"]
    assert item.text == ["Pršut", "500 g", "\U0001f600"]
    assert item.text_truncated is True


def test_jobs_item_as_json(api: Harness) -> None:
    result = api.run(lambda c: c.jobs.item("job_1", 0), json_response({"lines": []}))
    assert result.is_json
    assert not result.is_image
    assert result.content_type == "application/json"
    assert result.json() == {"lines": []}
    assert result.width is None


def test_jobs_item_as_a_remove_text_result(api: Harness) -> None:
    item = api.run(
        lambda c: c.jobs.item("job_1", 0),
        image_response({"X-Text-Removed": "3", "X-Text-Kept": "1", "server-timing": "ocr;dur=9"}),
    )
    direct = api.run(
        lambda c: c.remove_text(PNG),
        image_response({"X-Text-Removed": "3", "X-Text-Kept": "1", "server-timing": "ocr;dur=9"}),
    )
    result = item.remove_text()
    assert type(result) is RemoveTextResult
    assert (result.removed, result.kept) == (3, 1)
    assert result == direct  # the same reading as the synchronous method


def test_jobs_item_as_a_fix_result(api: Harness) -> None:
    headers = {"x-marketplace-passed": "false", "x-marketplace-findings": "too_small,blurry"}
    item = api.run(lambda c: c.jobs.item("job_1", 0), image_response(headers))
    direct = api.run(lambda c: c.fix(PNG, "etsy"), image_response(headers))
    result = item.fix()
    assert type(result) is FixResult
    assert result.passed is False
    assert result.findings == ["too_small", "blurry"]
    assert (result.content, result.width, result.height) == (PNG, 64, 48)
    assert result == direct

    passed = api.run(
        lambda c: c.jobs.item("job_1", 0), image_response({"x-marketplace-passed": "true"})
    ).fix()
    assert (passed.passed, passed.findings) == (True, [])


ITEM_RESULTS: list[
    tuple[str, dict[str, Any], dict[str, str], type[ImageResult], dict[str, Any]]
] = [
    # the method, its arguments, the result's headers, the result's type and own fields
    ("crop", {"aspect": "1:1"}, {"x-subject-found": "false"}, CropResult, {"subject_found": False}),
    ("vectorize", {}, {"x-paths": "23"}, VectorizeResult, {"paths": 23}),
    ("blur_faces", {}, {"x-faces": "3"}, BlurFacesResult, {"faces": 3}),
    (
        "restore_faces",
        {},
        {"x-faces": "2", "x-faces-skipped": "1"},
        RestoreFacesResult,
        {"faces": 2, "faces_skipped": 1},
    ),
    (
        "id_photo",
        {"document": "us-passport"},
        {
            "x-id-photo-passed": "false",
            "x-id-photo-findings": "head_tilted,low_resolution",
            "x-id-photo-head-mm": "30.0",
        },
        IdPhotoResult,
        {"passed": False, "findings": ["head_tilted", "low_resolution"], "head_mm": 30.0},
    ),
    ("select", {"point": (1, 2)}, {"x-select-score": "0.931"}, SelectResult, {"score": 0.931}),
]


@pytest.mark.parametrize(("method", "arguments", "headers", "cls", "fields"), ITEM_RESULTS)
def test_jobs_item_as_the_result_of_its_operation(
    api: Harness,
    method: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
    cls: type[ImageResult],
    fields: dict[str, Any],
) -> None:
    item = api.run(lambda c: c.jobs.item("job_1", 0), image_response(headers))
    direct = api.run(lambda c: getattr(c, method)(PNG, **arguments), image_response(headers))
    result = getattr(item, method)()
    assert type(result) is cls
    assert {name: getattr(result, name) for name in fields} == fields
    assert (result.content, result.width, result.height) == (PNG, 64, 48)
    assert result == direct  # the same reading as the client's method


@pytest.mark.parametrize(("method", "arguments", "headers", "cls", "fields"), ITEM_RESULTS)
def test_jobs_item_of_another_operation_is_an_error(
    api: Harness,
    method: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
    cls: type[ImageResult],
    fields: dict[str, Any],
) -> None:
    from photos_sh import APIError, PhotosError

    item = api.run(lambda c: c.jobs.item("job_1", 0), image_response())
    operation = method.replace("_", "-")
    with pytest.raises(PhotosError, match=f"not the result of a {operation} job") as caught:
        getattr(item, method)()
    assert not isinstance(caught.value, APIError)


def test_jobs_item_as_a_remove_background_result(api: Harness) -> None:
    headers = {"x-subject-found": "false", "server-timing": "model;dur=420"}
    item = api.run(lambda c: c.jobs.item("job_1", 0), image_response(headers))
    direct = api.run(
        lambda c: c.remove_background(PNG, width=64, height=48), image_response(headers)
    )
    result = item.remove_background()
    assert type(result) is RemoveBackgroundResult
    assert result.subject_found is False  # no subject was found
    assert (result.content, result.width, result.height) == (PNG, 64, 48)
    assert result == direct  # the same reading as the client's method

    # The header is absent when a subject was found: unknown, and not an error.
    usual = api.run(lambda c: c.jobs.item("job_1", 0), image_response()).remove_background()
    assert type(usual) is RemoveBackgroundResult
    assert usual.subject_found is None
    assert usual.content == PNG


def test_jobs_item_as_an_svg(api: Harness) -> None:
    item = api.run(lambda c: c.jobs.item("job_1", 0), svg_response({"x-paths": "2"}))
    assert item.is_image
    assert not item.is_json
    assert item.content_type == "image/svg+xml"
    traced = item.vectorize()
    assert (traced.paths, traced.content, traced.width, traced.height) == (2, SVG, 100, 80)


def test_jobs_item_without_the_headers_is_an_error(api: Harness) -> None:
    from photos_sh import APIError, PhotosError

    item = api.run(lambda c: c.jobs.item("job_1", 0), image_response())
    with pytest.raises(PhotosError, match="no x-text-removed header") as text:
        item.remove_text()
    with pytest.raises(PhotosError, match="no x-marketplace-passed header") as fix:
        item.fix()
    assert not isinstance(text.value, APIError)
    assert not isinstance(fix.value, APIError)

    # A fix result is not a remove-text result, and the other way round.
    fixed = api.run(
        lambda c: c.jobs.item("job_1", 0), image_response({"x-marketplace-passed": "true"})
    )
    with pytest.raises(PhotosError, match="remove-text"):
        fixed.remove_text()


def test_a_job_item_result_built_by_hand_reads_any_header_case() -> None:
    item = JobItemResult(content=PNG, headers={"X-Text-Removed": "2", "X-TEXT-KEPT": "5"})
    assert (item.remove_text().removed, item.remove_text().kept) == (2, 5)


def test_jobs_wait_polls_until_completed(api: Harness) -> None:
    running = {**JOB, "status": "running"}
    done = {**JOB, "status": "completed"}
    result = api.run(
        lambda c: c.jobs.wait("job_1", poll_interval=0.25),
        [json_response(JOB), json_response(running), json_response(done)],
    )
    assert result == done
    assert [r.url.path for r in api.requests] == ["/api/v1/jobs/job_1"] * 3
    assert api.sleeps == [0.25, 0.25]


def test_jobs_wait_uses_two_seconds_by_default(api: Harness) -> None:
    done = {**JOB, "status": "completed"}
    api.run(lambda c: c.jobs.wait("job_1"), [json_response(JOB), json_response(done)])
    assert api.sleeps == [2.0]


def test_jobs_wait_times_out(api: Harness) -> None:
    from photos_sh import JobTimeoutError

    with pytest.raises(JobTimeoutError, match="job_1 did not complete") as caught:
        api.run(lambda c: c.jobs.wait("job_1", timeout=0), json_response(JOB))
    assert caught.value.job == JOB
    assert len(api.requests) == 1


# --- results --------------------------------------------------------------------------


def test_save_writes_the_bytes(api: Harness, tmp_path: Path) -> None:
    result = api.run(lambda c: c.resize(PNG, width=10), image_response())
    result.save(tmp_path / "out.png")
    assert (tmp_path / "out.png").read_bytes() == PNG
    result.save(str(tmp_path / "out2.png"))
    assert (tmp_path / "out2.png").read_bytes() == PNG


def test_image_result_repr_leaves_out_the_bytes(api: Harness) -> None:
    result = api.run(lambda c: c.resize(PNG, width=10), image_response())
    assert "content=" not in repr(result)
    assert "width=64" in repr(result)


def test_an_unreadable_success_is_a_library_error(api: Harness) -> None:
    from photos_sh import APIError, PhotosError

    with pytest.raises(PhotosError, match="could not read the response") as caught:
        api.run(lambda c: c.account(), httpx.Response(200, content=b"<html>"))
    assert not isinstance(caught.value, APIError)
