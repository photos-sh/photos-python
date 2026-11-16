"""Configuration, errors and retries."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Optional

import httpx
import pytest
from conftest import PNG, Harness, error_response, image_response, json_response, parts_of

import photos_sh
from photos_sh import (
    AccountSuspendedError,
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncJobs,
    AsyncPhotos,
    AuthenticationError,
    BadRequestError,
    BusyError,
    InternalServerError,
    Jobs,
    ModelUnavailableError,
    NotFoundError,
    PayloadTooLargeError,
    PaymentRequiredError,
    Photos,
    PhotosError,
    UnprocessableError,
    UnsupportedFormatError,
)

# --- configuration --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOTOS_API_KEY", raising=False)
    monkeypatch.delenv("PHOTOS_BASE_URL", raising=False)


@pytest.mark.parametrize("cls", [Photos, AsyncPhotos])
def test_a_missing_key_is_an_error_at_construction(cls: Any) -> None:
    with pytest.raises(PhotosError, match="PHOTOS_API_KEY"):
        cls()
    with pytest.raises(PhotosError, match="PHOTOS_API_KEY"):
        cls(api_key="")


def test_key_and_base_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOTOS_API_KEY", "env-key")
    monkeypatch.setenv("PHOTOS_BASE_URL", "http://localhost:8080/")
    with Photos() as client:
        assert client.api_key == "env-key"
        assert client.base_url == "http://localhost:8080"
    with Photos("arg-key", base_url="http://other/api//") as client:
        assert client.api_key == "arg-key"
        assert client.base_url == "http://other/api"


def test_defaults() -> None:
    with Photos("k") as client:
        assert client.base_url == "https://api.photos.sh" == photos_sh.DEFAULT_BASE_URL
        assert client.max_retries == 2 == photos_sh.DEFAULT_MAX_RETRIES
        assert client._timeout == 120.0 == photos_sh.DEFAULT_TIMEOUT
        assert isinstance(client.jobs, Jobs)
        assert "k" not in repr(client)


def test_negative_retries_are_refused() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        Photos("k", max_retries=-1)


def test_headers_and_url(api: Harness) -> None:
    api.run(lambda c: c.account(), json_response({}), api_key="secret", base_url="http://h:1/x/")
    request = api.request
    assert str(request.url) == "http://h:1/x/v1/account"
    assert request.headers["authorization"] == "Bearer secret"
    assert request.headers["user-agent"] == f"photos-sh-python/{photos_sh.__version__}"
    assert photos_sh.__version__ == "1.1.0"


def test_timeout_is_passed_to_the_request(api: Harness) -> None:
    api.run(lambda c: c.account(), json_response({}), timeout=7.5)
    assert api.request.extensions["timeout"] == {
        "connect": 7.5,
        "read": 7.5,
        "write": 7.5,
        "pool": 7.5,
    }
    api.requests.clear()
    api.run(lambda c: c.account(), json_response({}), timeout=httpx.Timeout(3.0, read=60.0))
    assert api.request.extensions["timeout"]["read"] == 60.0


def test_a_supplied_http_client_keeps_its_timeout_and_stays_open() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response({})

    http_client = httpx.Client(transport=httpx.MockTransport(handle), timeout=11.0)
    with Photos("k", http_client=http_client) as client:
        client.account()
    assert seen[0].extensions["timeout"]["read"] == 11.0
    assert not http_client.is_closed
    http_client.close()


def test_the_library_closes_its_own_http_client() -> None:
    client = Photos("k")
    assert not client._http.is_closed
    client.close()
    assert client._http.is_closed

    async def go() -> None:
        own = AsyncPhotos("k")
        assert isinstance(own.jobs, AsyncJobs)
        await own.aclose()
        assert own._http.is_closed
        http_client = httpx.AsyncClient()
        async with AsyncPhotos("k", http_client=http_client):
            pass
        assert not http_client.is_closed
        await http_client.aclose()

    asyncio.run(go())


# --- the two clients are the same -----------------------------------------------------


def public(cls: type) -> dict[str, Any]:
    skip = {"close", "aclose"}
    return {
        name: member
        for name, member in vars(cls).items()
        if not name.startswith("_") and name not in skip and callable(member)
    }


def signature(function: Any, names: dict[str, str]) -> str:
    text = str(inspect.signature(function))
    for async_name, sync_name in names.items():
        text = text.replace(async_name, sync_name)
    return text


@pytest.mark.parametrize(("sync", "asynchronous"), [(Photos, AsyncPhotos), (Jobs, AsyncJobs)])
def test_sync_and_async_have_the_same_methods(sync: type, asynchronous: type) -> None:
    names = {"AsyncPhotos": "Photos", "AsyncJobs": "Jobs"}
    sync_methods, async_methods = public(sync), public(asynchronous)
    assert list(sync_methods) == list(async_methods)
    assert len(sync_methods) >= 6
    for name, method in sync_methods.items():
        twin = async_methods[name]
        assert not inspect.iscoroutinefunction(method), name
        assert inspect.iscoroutinefunction(twin), name
        assert signature(method, names) == signature(twin, names), name
        assert method.__doc__ == twin.__doc__, name


# --- errors ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (400, "bad_request", BadRequestError),
        (401, "unauthorized", AuthenticationError),
        (402, "payment_required", PaymentRequiredError),
        (403, "account_suspended", AccountSuspendedError),
        (404, "not_found", NotFoundError),
        (413, "payload_too_large", PayloadTooLargeError),
        (415, "unsupported_format", UnsupportedFormatError),
        (422, "unprocessable", UnprocessableError),
        (500, "internal", InternalServerError),
        (503, "model_unavailable", ModelUnavailableError),
        (418, "something_new", APIError),
    ],
)
def test_error_classes(api: Harness, status: int, code: str, cls: type[APIError]) -> None:
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.resize(PNG, width=1), error_response(status, code, "the message"))
    error = caught.value
    assert type(error) is cls
    assert isinstance(error, PhotosError)
    assert (error.status, error.code, error.message) == (status, code, "the message")
    assert error.retry_after is None
    assert error.body == {"error": {"code": code, "message": "the message"}}
    assert str(error) == f"{status} {code}: the message"
    assert len(api.requests) == 1  # never retried
    assert api.sleeps == []


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (401, AuthenticationError),
        (402, PaymentRequiredError),
        (404, APIError),
        (502, APIError),
    ],
)
def test_a_non_json_error_body(api: Harness, status: int, cls: type[APIError]) -> None:
    body = "<html>" + "x" * 500
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.account(), httpx.Response(status, text=body))
    error = caught.value
    assert type(error) is cls
    assert error.status == status
    assert error.code is None
    assert error.message == body[:200]
    assert error.body is None


def test_an_unknown_route_is_a_plain_api_error(api: Harness) -> None:
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.account(), httpx.Response(404))
    assert type(caught.value) is APIError
    assert (caught.value.status, caught.value.code) == (404, None)
    assert caught.value.message == "HTTP 404"
    assert str(caught.value) == "404: HTTP 404"


def test_json_that_is_not_the_error_format(api: Harness) -> None:
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.account(), httpx.Response(409, content=b'{"detail":"no"}'))
    assert caught.value.code is None
    assert caught.value.body == {"detail": "no"}
    assert caught.value.message == '{"detail":"no"}'


def test_health_raises_for_other_failures(api: Harness) -> None:
    with pytest.raises(InternalServerError):
        api.run(lambda c: c.health(), error_response(500, "internal"))
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.health(), httpx.Response(503, text="upstream down"))
    assert caught.value.status == 503
    assert caught.value.message == "upstream down"


# --- retries --------------------------------------------------------------------------

BUSY = error_response(503, "busy", "all workers are busy; retry shortly", **{"retry-after": "5"})


def test_503_is_retried_after_retry_after(api: Harness) -> None:
    result = api.run(lambda c: c.resize(PNG, width=1), [BUSY, BUSY, image_response()])
    assert result.content == PNG
    assert len(api.requests) == 3
    assert api.sleeps == [5.0, 5.0]
    for request in api.requests:  # each attempt carries the whole image again
        assert [p.content for p in parts_of(request)] == [PNG]


def test_503_without_retry_after_waits_one_then_two_seconds(api: Harness) -> None:
    busy = error_response(503, "busy")
    api.run(lambda c: c.account(), [busy, busy, json_response({})])
    assert api.sleeps == [1.0, 2.0]


def test_retry_after_is_capped(api: Harness) -> None:
    busy = error_response(503, "busy", **{"retry-after": "3600"})
    api.run(lambda c: c.account(), [busy, json_response({})])
    assert api.sleeps == [30.0]


def test_an_unreadable_retry_after_falls_back(api: Harness) -> None:
    busy = error_response(503, "busy", **{"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    api.run(lambda c: c.account(), [busy, json_response({})])
    assert api.sleeps == [1.0]


def test_busy_is_raised_when_retries_run_out(api: Harness) -> None:
    with pytest.raises(BusyError) as caught:
        api.run(lambda c: c.account(), BUSY)
    assert len(api.requests) == 3
    assert api.sleeps == [5.0, 5.0]
    assert caught.value.retry_after == 5.0
    assert caught.value.code == "busy"


@pytest.mark.parametrize(("max_retries", "requests"), [(0, 1), (1, 2), (4, 5)])
def test_max_retries(api: Harness, max_retries: int, requests: int) -> None:
    with pytest.raises(BusyError):
        api.run(lambda c: c.account(), BUSY, max_retries=max_retries)
    assert len(api.requests) == requests


def test_a_503_that_is_not_json_is_retried(api: Harness) -> None:
    result = api.run(
        lambda c: c.account(), [httpx.Response(503, text="bad gateway"), json_response({"a": 1})]
    )
    assert result == {"a": 1}
    assert api.sleeps == [1.0]


def test_model_unavailable_is_not_retried(api: Harness) -> None:
    with pytest.raises(ModelUnavailableError):
        api.run(lambda c: c.identify(PNG), error_response(503, "model_unavailable"))
    assert len(api.requests) == 1


def test_a_503_with_another_api_code_is_not_retried(api: Harness) -> None:
    with pytest.raises(APIError) as caught:
        api.run(lambda c: c.account(), error_response(503, "maintenance"))
    assert (caught.value.status, caught.value.code) == (503, "maintenance")
    assert len(api.requests) == 1


def test_a_503_with_other_json_is_retried(api: Harness) -> None:
    api.run(lambda c: c.account(), [json_response({"status": "loading"}, 503), json_response({})])
    assert len(api.requests) == 2


def test_creating_a_job_is_retried_on_503(api: Harness) -> None:
    job = {"id": "job_1", "status": "queued"}
    result = api.run(
        lambda c: c.jobs.create("resize", images=[PNG]), [BUSY, json_response(job, 202)]
    )
    assert result == job
    assert len(api.requests) == 2


def failing(error: Exception, then: Optional[httpx.Response] = None, times: int = 99) -> Any:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= times or then is None:
            raise error
        return then

    return handle


def test_a_connection_failure_is_retried(api: Harness) -> None:
    handler = failing(httpx.ConnectError("refused"), json_response({"a": 1}), times=2)
    assert api.run(lambda c: c.account(), handler) == {"a": 1}
    assert len(api.requests) == 3
    assert api.sleeps == [1.0, 2.0]


def test_a_connection_failure_is_raised_when_retries_run_out(api: Harness) -> None:
    with pytest.raises(APIConnectionError, match="refused") as caught:
        api.run(lambda c: c.resize(PNG, width=1), failing(httpx.ConnectError("refused")))
    assert not isinstance(caught.value, APITimeoutError)
    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert len(api.requests) == 3


def test_creating_a_job_is_not_retried_on_a_connection_failure(api: Harness) -> None:
    with pytest.raises(APIConnectionError):
        api.run(
            lambda c: c.jobs.create("resize", urls=["https://example.com/1.jpg"]),
            failing(httpx.ConnectError("refused")),
        )
    assert len(api.requests) == 1
    assert api.sleeps == []


def test_a_connect_timeout_is_retried_and_is_a_timeout_error(api: Harness) -> None:
    with pytest.raises(APITimeoutError) as caught:
        api.run(lambda c: c.account(), failing(httpx.ConnectTimeout("slow")))
    assert isinstance(caught.value, APIConnectionError)
    assert len(api.requests) == 3


def test_a_read_timeout_is_not_retried(api: Harness) -> None:
    with pytest.raises(APITimeoutError):
        api.run(lambda c: c.upscale(PNG), failing(httpx.ReadTimeout("slow")))
    assert len(api.requests) == 1


def test_a_broken_connection_is_retried(api: Harness) -> None:
    handler = failing(httpx.RemoteProtocolError("server disconnected"), image_response(), times=1)
    assert api.run(lambda c: c.upscale(PNG), handler).content == PNG
    assert len(api.requests) == 2
