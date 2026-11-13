"""Shared test helpers: a harness that runs one test body against both
clients, a multipart reader, a tiny PNG, and a real local HTTP server."""

from __future__ import annotations

import asyncio
import inspect
import struct
import threading
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional, Union

import httpx
import pytest

from photos_sh import AsyncPhotos, Photos

API_KEY = "test-key"
BASE_URL = "https://api.test/api"
DATA = Path(__file__).parent / "data"

Handler = Callable[[httpx.Request], httpx.Response]


Pixel = Callable[[int, int], tuple[int, int, int]]


def png(width: int = 64, height: int = 48, pixel: Optional[Pixel] = None) -> bytes:
    """A valid RGB PNG, made without an imaging library: a gradient, or ``pixel(x, y)``."""
    paint = pixel or (lambda x, y: (x * 255 // width, y * 255 // height, 128))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(
        b"\x00" + bytes(v for x in range(width) for v in paint(x, y)) for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


PNG = png()

#: 100 x 80: a blue box of 40 x 20 on white, with a white border all round.
BOXED = png(
    100, 80, lambda x, y: (20, 30, 200) if 20 <= x < 60 and 30 <= y < 50 else (255, 255, 255)
)


@dataclass
class Part:
    name: str
    filename: Optional[str]
    content: bytes


def multipart(content_type: str, body: bytes) -> list[Part]:
    """The parts of a multipart/form-data body, in order."""
    assert content_type.startswith("multipart/form-data"), content_type
    boundary = content_type.split("boundary=", 1)[1].strip('"').encode()
    parts = []
    for raw in body.split(b"--" + boundary)[1:-1]:
        head, _, content = raw.removeprefix(b"\r\n").partition(b"\r\n\r\n")
        disposition = next(
            line for line in head.decode().split("\r\n") if line.lower().startswith("content-disp")
        )
        fields = {
            k.strip(): v.strip('"')
            for k, _, v in (item.partition("=") for item in disposition.split(";")[1:])
        }
        parts.append(Part(fields["name"], fields.get("filename"), content.removesuffix(b"\r\n")))
    return parts


def parts_of(request: httpx.Request) -> list[Part]:
    return multipart(request.headers["content-type"], request.content)


def json_response(body: Any, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def error_response(status: int, code: str, message: str = "nope", **headers: str) -> httpx.Response:
    return json_response({"error": {"code": code, "message": message}}, status, **headers)


def image_response(headers: Optional[dict[str, str]] = None) -> httpx.Response:
    base = {"content-type": "image/png", "x-image-width": "64", "x-image-height": "48"}
    return httpx.Response(200, content=PNG, headers={**base, **(headers or {})})


def fresh(response: httpx.Response) -> httpx.Response:
    """A copy, so one canned response can answer several requests of either client."""
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


@dataclass
class Harness:
    """Runs a call against the sync or the async client over a mock transport.

    ``run(lambda c: c.resize(...))`` returns the result for either kind; the
    requests the client made and the pauses it took are recorded.
    """

    kind: str
    requests: list[httpx.Request] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    def run(
        self,
        call: Callable[[Any], Any],
        handler: Union[Handler, list[httpx.Response], httpx.Response],
        **options: Any,
    ) -> Any:
        def handle(request: httpx.Request) -> httpx.Response:
            request.read()
            self.requests.append(request)
            if isinstance(handler, httpx.Response):
                return fresh(handler)
            if isinstance(handler, list):
                return fresh(handler[min(len(self.requests), len(handler)) - 1])
            return fresh(handler(request))

        transport = httpx.MockTransport(handle)
        options.setdefault("api_key", API_KEY)
        options.setdefault("base_url", BASE_URL)

        if self.kind == "sync":
            with Photos(http_client=httpx.Client(transport=transport), **options) as client:
                client._sleep = self.sleeps.append  # type: ignore[method-assign, assignment]
                return call(client)

        async def record(seconds: float) -> None:
            self.sleeps.append(seconds)

        async def go() -> Any:
            http_client = httpx.AsyncClient(transport=transport)
            async with AsyncPhotos(http_client=http_client, **options) as client:
                client._sleep = record  # type: ignore[method-assign]
                result = call(client)
                return await result if inspect.isawaitable(result) else result

        return asyncio.run(go())

    @property
    def request(self) -> httpx.Request:
        assert len(self.requests) == 1, f"expected one request, got {len(self.requests)}"
        return self.requests[0]


@pytest.fixture(params=["sync", "async"])
def api(request: pytest.FixtureRequest) -> Harness:
    return Harness(request.param)


# --- a real HTTP server ---------------------------------------------------------------


@dataclass
class Received:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Reply:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


class LocalServer:
    """An ``http.server`` on a free local port, answering with scripted replies."""

    def __init__(self) -> None:
        self.received: list[Received] = []
        self.replies: list[Reply] = []
        self.arrived = threading.Condition()
        owner = self

        class RequestHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                headers = {k.lower(): v for k, v in self.headers.items()}
                with owner.arrived:
                    owner.received.append(Received(self.command, self.path, headers, body))
                    n = len(owner.received)
                    owner.arrived.notify_all()
                reply = owner.replies[min(n, len(owner.replies)) - 1] if owner.replies else Reply()
                self.send_response(reply.status)
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            do_GET = do_POST = do_DELETE = _handle

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def wait_for(self, count: int, timeout: float = 30.0) -> list[Received]:
        """Blocks until ``count`` requests have arrived."""
        with self.arrived:
            assert self.arrived.wait_for(lambda: len(self.received) >= count, timeout), (
                f"only {len(self.received)} of {count} requests arrived"
            )
            return list(self.received)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


@pytest.fixture
def server() -> Iterator[LocalServer]:
    local = LocalServer()
    yield local
    local.close()
