"""The clients over real sockets, against an ``http.server`` on this machine."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from conftest import PNG, LocalServer, Reply, multipart

from photos_sh import APIConnectionError, AsyncPhotos, BusyError, Photos

IMAGE = Reply(
    200,
    {
        "Content-Type": "image/png",
        "X-Image-Width": "64",
        "X-Image-Height": "48",
        "Server-Timing": "resize;dur=2",
    },
    PNG,
)
BUSY = Reply(
    503,
    {"Content-Type": "application/json", "Retry-After": "0"},
    json.dumps({"error": {"code": "busy", "message": "all workers are busy"}}).encode(),
)


def check_resize(server: LocalServer, result: Any, tmp_path: Path) -> None:
    (received,) = server.received
    assert received.method == "POST"
    assert received.path == "/api/v1/resize?width=32&enlarge=false&format=png"
    assert received.headers["authorization"] == "Bearer local-key"
    assert received.headers["user-agent"].startswith("photos-sh-python/")
    assert int(received.headers["content-length"]) == len(received.body)
    (part,) = multipart(received.headers["content-type"], received.body)
    assert (part.name, part.filename, part.content) == ("image", "in.png", PNG)

    assert result.content == PNG
    assert result.content_type == "image/png"
    assert (result.width, result.height, result.quality) == (64, 48, None)
    assert result.server_timing == "resize;dur=2"
    result.save(tmp_path / "out.png")
    assert (tmp_path / "out.png").read_bytes() == PNG


def test_a_request_end_to_end(server: LocalServer, tmp_path: Path) -> None:
    server.replies = [IMAGE]
    (tmp_path / "in.png").write_bytes(PNG)
    with Photos("local-key", base_url=server.url + "/api/") as photos:
        result = photos.resize(tmp_path / "in.png", width=32, enlarge=False, format="png")
    check_resize(server, result, tmp_path)


async def test_a_request_end_to_end_async(server: LocalServer, tmp_path: Path) -> None:
    server.replies = [IMAGE]
    (tmp_path / "in.png").write_bytes(PNG)
    async with AsyncPhotos("local-key", base_url=server.url + "/api/") as photos:
        result = await photos.resize(tmp_path / "in.png", width=32, enlarge=False, format="png")
    check_resize(server, result, tmp_path)


def test_a_second_image_end_to_end(server: LocalServer, tmp_path: Path) -> None:
    server.replies = [Reply(200, {**IMAGE.headers, "X-Subject-Found": "false"}, PNG)]
    (tmp_path / "beach.jpg").write_bytes(b"beach")
    with Photos("local-key", base_url=server.url) as photos:
        result = photos.remove_background(
            PNG, width=200, height=100, background_image=tmp_path / "beach.jpg"
        )
    (received,) = server.received
    assert received.path == "/v1/remove-background?width=200&height=100"
    image, background = multipart(received.headers["content-type"], received.body)
    assert (image.name, image.filename, image.content) == ("image", "image", PNG)
    assert (background.name, background.filename) == ("background", "beach.jpg")
    assert background.content == b"beach"
    assert result.subject_found is False
    assert (result.width, result.height) == (64, 48)


async def test_points_that_repeat_end_to_end_async(server: LocalServer) -> None:
    server.replies = [Reply(200, {**IMAGE.headers, "X-Select-Score": "0.931"}, PNG)]
    async with AsyncPhotos("local-key", base_url=server.url) as photos:
        result = await photos.select(
            PNG, point=[(120, 80), (200.5, 90)], exclude=(10, 10), box=(40, 30, 400, 300)
        )
    (received,) = server.received
    assert received.path == (
        "/v1/select?point=120%2C80&point=200.5%2C90&exclude=10%2C10&box=40%2C30%2C400%2C300"
    )
    (part,) = multipart(received.headers["content-type"], received.body)
    assert (part.name, part.content) == ("image", PNG)
    assert result.score == 0.931


def test_a_503_is_retried(server: LocalServer) -> None:
    server.replies = [BUSY, BUSY, IMAGE]
    with Photos("local-key", base_url=server.url) as photos:
        result = photos.upscale(PNG, scale=2)
    assert result.content == PNG
    assert [r.path for r in server.received] == ["/v1/upscale?scale=2"] * 3
    for received in server.received:  # each attempt carries the whole image again
        (part,) = multipart(received.headers["content-type"], received.body)
        assert part.content == PNG


async def test_a_503_is_retried_async(server: LocalServer) -> None:
    server.replies = [BUSY, IMAGE]
    async with AsyncPhotos("local-key", base_url=server.url) as photos:
        result = await photos.upscale(PNG, scale=2)
    assert result.content == PNG
    assert len(server.received) == 2


def test_busy_after_the_retries(server: LocalServer) -> None:
    server.replies = [BUSY]
    photos = Photos("local-key", base_url=server.url, max_retries=1)
    with pytest.raises(BusyError) as caught:
        photos.account()
    photos.close()
    assert caught.value.retry_after == 0
    assert len(server.received) == 2


def test_health_while_loading(server: LocalServer) -> None:
    server.replies = [Reply(503, {"Content-Type": "application/json"}, b'{"status":"loading"}')]
    with Photos("local-key", base_url=server.url) as photos:
        assert photos.health() == "loading"
    assert len(server.received) == 1


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


def test_a_connection_failure() -> None:
    with Photos("local-key", base_url=f"http://127.0.0.1:{closed_port()}") as photos:
        pauses: list[float] = []
        photos._sleep = pauses.append  # type: ignore[method-assign, assignment]
        with pytest.raises(APIConnectionError, match="could not get a response"):
            photos.account()
    assert pauses == [1.0, 2.0]


async def test_a_connection_failure_async() -> None:
    async with AsyncPhotos(
        "local-key", base_url=f"http://127.0.0.1:{closed_port()}", max_retries=0
    ) as photos:
        with pytest.raises(APIConnectionError):
            await photos.account()
