import pytest

from calls.signatures import SignatureError, compute_signature, verify_signature

BODY = b'{"event_id": "evt_1"}'
NOW = 1_700_000_000


def sign(ts=NOW, secret="s3cret", body=BODY):
    return "sha256=" + compute_signature(secret, str(ts), body)


def test_valid_signature_passes():
    verify_signature("s3cret", str(NOW), sign(), BODY, now=NOW)


def test_signature_without_prefix_is_accepted():
    verify_signature("s3cret", str(NOW), sign().removeprefix("sha256="), BODY, now=NOW)


@pytest.mark.parametrize(
    "secret,timestamp,signature,body,message",
    [
        ("s3cret", str(NOW), sign(secret="wrong"), BODY, "mismatch"),
        ("s3cret", str(NOW), sign(), b'{"event_id": "evt_2"}', "mismatch"),
        ("s3cret", str(NOW), None, BODY, "missing"),
        ("s3cret", None, sign(), BODY, "missing"),
        ("s3cret", "not-a-number", sign(), BODY, "invalid timestamp"),
        ("", str(NOW), sign(), BODY, "not configured"),
    ],
)
def test_invalid_signatures_are_rejected(secret, timestamp, signature, body, message):
    with pytest.raises(SignatureError, match=message):
        verify_signature(secret, timestamp, signature, body, now=NOW)


def test_old_timestamp_is_rejected_even_if_signature_matches():
    old = NOW - 301
    with pytest.raises(SignatureError, match="tolerance"):
        verify_signature("s3cret", str(old), sign(ts=old), BODY, tolerance=300, now=NOW)


@pytest.mark.django_db
def test_webhook_endpoint_rejects_bad_signature(post_webhook):
    from tests.conftest import make_event

    response = post_webhook(make_event("evt_1", "call.started"), secret="not-the-secret")
    assert response.status_code == 401


def test_any_of_several_secrets_is_accepted():
    verify_signature(["new-secret", "s3cret"], str(NOW), sign(), BODY, now=NOW)
    with pytest.raises(SignatureError, match="mismatch"):
        verify_signature(["new-secret", "other"], str(NOW), sign(), BODY, now=NOW)


@pytest.mark.django_db
def test_webhook_endpoint_rejects_unsigned_request(tenant):
    response = tenant.key_client().post("/api/webhooks/calls/", {"event_id": "x"}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_webhook_endpoint_requires_an_api_key(api_client):
    response = api_client.post("/api/webhooks/calls/", {"event_id": "x"}, format="json")
    assert response.status_code == 401
