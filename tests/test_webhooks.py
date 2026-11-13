from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from photos_sh import PhotosError, WebhookVerificationError, webhooks

SECRET = "whsec_test"
NOW = 1_800_000_000
BODY = json.dumps(
    {"type": "job.completed", "job": {"id": "job_1", "status": "completed", "naïve": "ž"}},
    ensure_ascii=False,
).encode()


def header(body: bytes = BODY, secret: str = SECRET, t: int = NOW) -> str:
    # Computed independently of the library.
    digest = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def test_a_valid_delivery() -> None:
    event = webhooks.verify(BODY, header(), SECRET, now=NOW)
    assert event["type"] == "job.completed"
    assert event["job"]["id"] == "job_1"
    assert event == json.loads(BODY)


def test_the_body_may_be_text() -> None:
    assert webhooks.verify(BODY.decode(), header(), SECRET, now=NOW)["type"] == "job.completed"


def test_the_current_time_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: NOW + 10.0)
    assert webhooks.verify(BODY, header(), SECRET)["type"] == "job.completed"
    monkeypatch.setattr("time.time", lambda: NOW + 301.0)
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        webhooks.verify(BODY, header(), SECRET)


def test_sign_matches_verify() -> None:
    assert webhooks.sign(BODY, SECRET, NOW) == header()
    assert webhooks.sign(BODY.decode(), SECRET, NOW) == header()


def test_a_tampered_body() -> None:
    with pytest.raises(WebhookVerificationError, match="does not match"):
        webhooks.verify(BODY.replace(b"job_1", b"job_2"), header(), SECRET, now=NOW)


def test_a_wrong_secret() -> None:
    with pytest.raises(WebhookVerificationError, match="does not match"):
        webhooks.verify(BODY, header(), "whsec_other", now=NOW)


def test_a_changed_timestamp_breaks_the_signature() -> None:
    forged = header().replace(f"t={NOW}", f"t={NOW + 1}")
    with pytest.raises(WebhookVerificationError, match="does not match"):
        webhooks.verify(BODY, forged, SECRET, now=NOW)


@pytest.mark.parametrize("offset", [-301, 301, 100_000])
def test_an_old_or_future_timestamp(offset: int) -> None:
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        webhooks.verify(BODY, header(), SECRET, now=NOW + offset)


@pytest.mark.parametrize("offset", [-300, 0, 300])
def test_timestamps_within_the_tolerance(offset: int) -> None:
    assert webhooks.verify(BODY, header(), SECRET, now=NOW + offset)


def test_a_custom_tolerance() -> None:
    assert webhooks.verify(BODY, header(), SECRET, tolerance=1000, now=NOW + 900)
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        webhooks.verify(BODY, header(), SECRET, 10, NOW + 11)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        None,
        "garbage",
        "v1=abc",
        f"t={NOW}",
        f"t={NOW},v0=abc",
        "t=soon,v1=abc",
        "t=-5,v1=abc",
        f"t={NOW};v1=abc",
    ],
)
def test_a_malformed_header(bad: str | None) -> None:
    with pytest.raises(WebhookVerificationError, match="header"):
        webhooks.verify(BODY, bad, SECRET, now=NOW)


def test_an_empty_secret() -> None:
    with pytest.raises(WebhookVerificationError, match="secret"):
        webhooks.verify(BODY, header(secret=""), "", now=NOW)


def test_spaces_case_and_several_signatures_are_tolerated() -> None:
    t, v1 = header().split(",")
    assert webhooks.verify(BODY, f" {t} , {v1.upper().replace('V1', 'v1')} ", SECRET, now=NOW)
    assert webhooks.verify(BODY, f"{t},v1={'0' * 64},{v1}", SECRET, now=NOW)


def test_a_signed_body_that_is_not_an_event() -> None:
    with pytest.raises(WebhookVerificationError, match="JSON"):
        webhooks.verify(b"not json", header(b"not json"), SECRET, now=NOW)
    with pytest.raises(WebhookVerificationError, match="JSON object"):
        webhooks.verify(b"[1]", header(b"[1]"), SECRET, now=NOW)


def test_the_error_is_a_photos_error() -> None:
    assert issubclass(WebhookVerificationError, PhotosError)
    assert webhooks.SIGNATURE_HEADER == "Photos-Signature"
