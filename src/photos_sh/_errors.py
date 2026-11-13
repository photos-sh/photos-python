"""Everything the library raises."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ._types import Job


class PhotosError(Exception):
    """Base class of every error this library raises."""


class APIError(PhotosError):
    """The API answered with an error status.

    ``code`` is the API's own error code (``"bad_request"``, ``"busy"``, ...),
    or ``None`` when the body was not the API's JSON error format.
    """

    status: int
    code: Optional[str]
    message: str
    retry_after: Optional[float]
    body: Any

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: Optional[str] = None,
        retry_after: Optional[float] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.body = body

    def __str__(self) -> str:
        label = f"{self.status} {self.code}" if self.code else str(self.status)
        return f"{label}: {self.message}"


class BadRequestError(APIError):
    """400 ``bad_request``: a parameter or the image is wrong."""


class AuthenticationError(APIError):
    """401 ``unauthorized``: the API key is missing or invalid."""


class PaymentRequiredError(APIError):
    """402 ``payment_required``: the account is out of credits."""


class AccountSuspendedError(APIError):
    """403 ``account_suspended``."""


class NotFoundError(APIError):
    """404 ``not_found``: no such job or job item.

    A 404 without that code (an unknown route, a wrong base URL) is a plain
    :class:`APIError`.
    """


class PayloadTooLargeError(APIError):
    """413 ``payload_too_large``: the upload or the image is too big."""


class UnsupportedFormatError(APIError):
    """415 ``unsupported_format``: the server cannot read this image format."""


class UnprocessableError(APIError):
    """422 ``unprocessable``: the request is valid but cannot be carried out."""


class BusyError(APIError):
    """503 ``busy``: every worker is busy. Raised once the retries are used up."""


class ModelUnavailableError(APIError):
    """503 ``model_unavailable``: this tool is not available on the server."""


class InternalServerError(APIError):
    """500 ``internal``."""


class APIConnectionError(PhotosError):
    """No response arrived: the connection failed or broke."""


class APITimeoutError(APIConnectionError):
    """The request timed out."""


class JobTimeoutError(PhotosError):
    """``jobs.wait`` gave up before the job completed. ``job`` is its last known state."""

    job: Job

    def __init__(self, message: str, *, job: Job) -> None:
        super().__init__(message)
        self.job = job


class WebhookVerificationError(PhotosError):
    """A webhook delivery did not pass verification."""


_BY_CODE: dict[str, type[APIError]] = {
    "bad_request": BadRequestError,
    "unauthorized": AuthenticationError,
    "payment_required": PaymentRequiredError,
    "account_suspended": AccountSuspendedError,
    "not_found": NotFoundError,
    "payload_too_large": PayloadTooLargeError,
    "unsupported_format": UnsupportedFormatError,
    "unprocessable": UnprocessableError,
    "busy": BusyError,
    "model_unavailable": ModelUnavailableError,
    "internal": InternalServerError,
}

_BY_STATUS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: AccountSuspendedError,
    413: PayloadTooLargeError,
    415: UnsupportedFormatError,
    422: UnprocessableError,
    500: InternalServerError,
}


def error_class(status: int, code: Optional[str]) -> type[APIError]:
    """The class for an error response: by the API's code, else by status."""
    if code is not None and code in _BY_CODE:
        return _BY_CODE[code]
    return _BY_STATUS.get(status, APIError)
