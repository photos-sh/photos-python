"""Verifying webhook deliveries. Needs no client: see :func:`verify`."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional, Union, cast

from ._errors import WebhookVerificationError
from ._types import WebhookEvent

#: The header that carries the signature.
SIGNATURE_HEADER = "Photos-Signature"

DEFAULT_TOLERANCE = 300


def sign(body: Union[bytes, str], secret: str, timestamp: int) -> str:
    """The ``Photos-Signature`` header value for ``body`` at ``timestamp`` (for tests)."""
    raw = body.encode() if isinstance(body, str) else bytes(body)
    return f"t={timestamp},v1={_digest(raw, secret, str(timestamp))}"


def verify(
    body: Union[bytes, str],
    header: Optional[str],
    secret: str,
    tolerance: float = DEFAULT_TOLERANCE,
    now: Optional[float] = None,
) -> WebhookEvent:
    """Check a delivery's signature and age, and return the event.

    ``body`` is the raw request body, exactly as received (do not re-encode
    parsed JSON); ``header`` the ``Photos-Signature`` header; ``secret`` the
    key from ``client.webhook_secret()``. ``tolerance`` is the accepted
    distance in seconds between the signature's timestamp and ``now`` (Unix
    seconds; the current time by default).

    Raises :class:`~photos_sh.WebhookVerificationError` when anything is off.
    """
    if not secret:
        raise WebhookVerificationError("no webhook secret given")
    if not header:
        raise WebhookVerificationError(f"no {SIGNATURE_HEADER} header")
    raw = body.encode() if isinstance(body, str) else bytes(body)

    timestamp: Optional[str] = None
    signatures: list[str] = []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t":
            timestamp = value
        elif name == "v1":
            signatures.append(value)
    if timestamp is None or not timestamp.isascii() or not timestamp.isdigit() or not signatures:
        raise WebhookVerificationError(
            f"malformed {SIGNATURE_HEADER} header: expected t=<unix seconds>,v1=<hex>"
        )

    expected = _digest(raw, secret, timestamp).encode()
    # Compare every candidate, so the time taken does not depend on which matched.
    matched = False
    for signature in signatures:
        matched |= hmac.compare_digest(expected, signature.strip().lower().encode())
    if not matched:
        raise WebhookVerificationError("the signature does not match the body")

    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance:
        raise WebhookVerificationError(
            f"the signature's timestamp is more than {tolerance:g} s from now"
        )

    try:
        event = json.loads(raw)
    except ValueError as e:
        raise WebhookVerificationError("the body is not valid JSON") from e
    if not isinstance(event, dict):
        raise WebhookVerificationError("the body is not a JSON object")
    return cast(WebhookEvent, event)


def _digest(raw: bytes, secret: str, timestamp: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()


__all__ = [
    "DEFAULT_TOLERANCE",
    "SIGNATURE_HEADER",
    "WebhookEvent",
    "WebhookVerificationError",
    "sign",
    "verify",
]
