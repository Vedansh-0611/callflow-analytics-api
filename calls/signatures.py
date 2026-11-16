"""HMAC-SHA256 webhook signatures.

The provider signs `"<timestamp>.<raw body>"` with a shared secret and sends:
    X-Webhook-Timestamp: 1700000000
    X-Webhook-Signature: sha256=<hex digest>

Including the timestamp in the signed message means an attacker cannot replay
an old request with a fresh timestamp, and the tolerance window rejects old ones.
"""
import hashlib
import hmac
import time


class SignatureError(Exception):
    pass


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(secret, timestamp, signature, body, tolerance=300, now=None):
    """Raise SignatureError unless the request is signed and recent.

    `secret` can be a list, so a request signed with either the current or the
    just-rotated secret is accepted during the rotation grace period.
    """
    candidates = [secret] if isinstance(secret, str) else list(secret)
    secrets = [s for s in candidates if s]
    if not secrets:
        raise SignatureError("webhook secret is not configured")
    if not timestamp or not signature:
        raise SignatureError("missing signature headers")

    try:
        sent_at = int(timestamp)
    except ValueError:
        raise SignatureError("invalid timestamp")

    now = time.time() if now is None else now
    if abs(now - sent_at) > tolerance:
        raise SignatureError("timestamp outside tolerance window")

    provided = signature.removeprefix("sha256=")
    # compare_digest takes the same time whether the strings match early or late.
    if not any(hmac.compare_digest(compute_signature(s, timestamp, body), provided) for s in secrets):
        raise SignatureError("signature mismatch")
