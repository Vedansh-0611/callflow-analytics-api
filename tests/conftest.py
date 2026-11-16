import json
import time

import pytest
from rest_framework.test import APIClient

from calls.signatures import compute_signature

SECRET = "test-secret"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def post_webhook(api_client):
    """Send a correctly signed webhook, the same way a provider would."""

    def _post(payload, secret=SECRET, timestamp=None):
        body = json.dumps(payload).encode()
        ts = str(int(timestamp if timestamp is not None else time.time()))
        return api_client.post(
            "/api/webhooks/calls/",
            data=body,
            content_type="application/json",
            HTTP_X_WEBHOOK_TIMESTAMP=ts,
            HTTP_X_WEBHOOK_SIGNATURE="sha256=" + compute_signature(secret, ts, body),
        )

    return _post


def make_event(event_id, type_, call_id="call_1", timestamp="2026-01-10T10:00:00Z", **data):
    return {"event_id": event_id, "type": type_, "call_id": call_id, "timestamp": timestamp, "data": data}


def full_call(call_id="call_1", duration=125, end_reason="completed", tool_success=True):
    """A realistic sequence of events for one call."""
    return [
        make_event(f"{call_id}_1", "call.started", call_id, "2026-01-10T10:00:00Z",
                   agent_id="clinic-bot", direction="inbound", **{"from": "+919800000001", "to": "+918000000000"}),
        make_event(f"{call_id}_2", "transcript.chunk", call_id, "2026-01-10T10:00:05Z", speaker="agent", text="Hello!"),
        make_event(f"{call_id}_3", "transcript.chunk", call_id, "2026-01-10T10:00:10Z", speaker="caller", text="Hi"),
        make_event(f"{call_id}_4", "tool.called", call_id, "2026-01-10T10:01:00Z",
                   name="book_appointment", success=tool_success),
        make_event(f"{call_id}_5", "call.ended", call_id, "2026-01-10T10:02:05Z",
                   duration_seconds=duration, end_reason=end_reason,
                   usage={"model": "gpt-4o-mini", "prompt_tokens": 2000, "completion_tokens": 500}),
    ]
