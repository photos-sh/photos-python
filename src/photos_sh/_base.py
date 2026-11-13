"""What the sync and the async client share: configuration, the retry rules
and the reading of responses. Nothing here does I/O."""

from __future__ import annotations

import os
import time
from typing import Any, Optional, TypeVar, Union

import httpx

from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    JobTimeoutError,
    PhotosError,
    error_class,
)
from ._requests import Request
from ._types import Job
from ._version import __version__

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.photos.sh"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_DELAY = 30.0
USER_AGENT = f"photos-sh-python/{__version__}"

Timeout = Union[float, httpx.Timeout]


class BaseClient:
    api_key: str
    base_url: str
    max_retries: int

    def __init__(
        self,
        api_key: Optional[str],
        *,
        base_url: Optional[str],
        timeout: Optional[Timeout],
        max_retries: int,
        has_http_client: bool,
    ) -> None:
        api_key = api_key or os.environ.get("PHOTOS_API_KEY")
        if not api_key:
            raise PhotosError(
                "No API key: pass api_key or set the PHOTOS_API_KEY environment variable."
            )
        if max_retries < 0:
            raise ValueError("max_retries must be 0 or more")
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("PHOTOS_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.max_retries = max_retries
        # A caller's own HTTP client keeps its timeout unless one is given here.
        self._timeout: Optional[Timeout] = (
            timeout if timeout is not None or has_http_client else DEFAULT_TIMEOUT
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    # --- sending ------------------------------------------------------------------

    def _request_kwargs(self, request: Request[Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "method": request.method,
            "url": self.base_url + request.path,
            "headers": {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            },
        }
        if request.params:
            kwargs["params"] = request.params
        if request.files is not None:
            kwargs["files"] = request.files
        if request.data is not None:
            kwargs["data"] = request.data
        if request.json is not None:
            kwargs["json"] = request.json
        if self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return kwargs

    # --- retries ------------------------------------------------------------------

    def _delay_after_response(
        self, request: Request[Any], attempt: int, response: httpx.Response
    ) -> Optional[float]:
        """Seconds to wait before sending again, or None to take this response."""
        if response.status_code != 503 or not request.unavailable_is_error:
            return None
        if attempt >= self.max_retries:
            return None
        # Only a busy server is worth asking again (or a 503 that is not the API's own,
        # from a proxy in front of it): a tool the server does not have will not appear.
        if _error_fields(response)[0] not in ("busy", None):
            return None
        retry_after = _retry_after(response)
        if retry_after is not None:
            return min(retry_after, MAX_RETRY_DELAY)
        return float(2**attempt)

    def _delay_after_failure(
        self, request: Request[Any], attempt: int, error: httpx.HTTPError
    ) -> Optional[float]:
        """Seconds to wait before sending again, or None to give up."""
        if attempt >= self.max_retries or not request.retry_connection_errors:
            return None
        if not isinstance(error, httpx.TransportError):
            return None
        # A slow answer is not retried: only failing to reach the server is.
        if isinstance(error, httpx.TimeoutException) and not isinstance(
            error, httpx.ConnectTimeout
        ):
            return None
        return float(2**attempt)

    # --- reading ------------------------------------------------------------------

    def _finish(self, request: Request[T], response: httpx.Response) -> T:
        status = response.status_code
        ok = 200 <= status < 300 or (status == 503 and not request.unavailable_is_error)
        if ok:
            try:
                return request.parse(response)
            except (ValueError, KeyError, TypeError) as e:
                if 200 <= status < 300:
                    raise PhotosError(
                        f"could not read the response to {request.method} {request.path}: {e}"
                    ) from e
        raise api_error(response)


def connection_error(error: httpx.HTTPError) -> APIConnectionError:
    if isinstance(error, httpx.TimeoutException):
        return APITimeoutError(f"the request timed out: {error!r}")
    return APIConnectionError(f"could not get a response: {error!r}")


def _retry_after(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _error_fields(response: httpx.Response) -> tuple[Optional[str], Optional[str], Any]:
    """The API's error code and message, and the decoded body, if it is JSON."""
    try:
        body = response.json()
    except ValueError:
        return None, None, None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, None, body
    code, message = error.get("code"), error.get("message")
    return (
        code if isinstance(code, str) else None,
        message if isinstance(message, str) else None,
        body,
    )


def api_error(response: httpx.Response) -> APIError:
    code, message, body = _error_fields(response)
    if message is None:
        message = response.text[:200].strip() or f"HTTP {response.status_code}"
    return error_class(response.status_code, code)(
        message,
        status=response.status_code,
        code=code,
        retry_after=_retry_after(response),
        body=body,
    )


class Deadline:
    """The overall time limit of ``jobs.wait``."""

    def __init__(self, timeout: float, poll_interval: float) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval must be 0 or more")
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._end = time.monotonic() + timeout

    def next_pause(self, job: Job) -> float:
        """How long to pause before the next poll; raises when time is up."""
        left = self._end - time.monotonic()
        if left <= 0:
            raise JobTimeoutError(
                f"job {job['id']} did not complete within {self._timeout:g} s "
                f"(status {job['status']})",
                job=job,
            )
        return min(self._poll_interval, left)
