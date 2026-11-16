import pytest

from calls.models import Call, CallEvent
from tests.conftest import full_call, make_event

pytestmark = pytest.mark.django_db


def test_full_call_is_stored_and_summarized(post_webhook, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        for payload in full_call():
            assert post_webhook(payload).status_code == 202

    call = Call.objects.get(provider_call_id="call_1")
    assert call.status == Call.Status.COMPLETED
    assert call.agent_id == "clinic-bot"
    assert call.from_number == "+919800000001"
    assert call.duration_seconds == 125
    assert call.prompt_tokens == 2000
    assert call.events.count() == 5
    # summarize_call ran (eager mode) after the call.ended commit
    assert call.summarized_at is not None
    assert call.transcript_turns == 2
    assert call.tool_calls == 1
    assert "booking_made" in call.outcome_tags


def test_duplicate_event_is_ignored(post_webhook):
    payload = make_event("evt_dup", "call.started", agent_id="a1")

    first = post_webhook(payload)
    second = post_webhook(payload)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}
    assert CallEvent.objects.filter(event_id="evt_dup").count() == 1


def test_events_arriving_out_of_order(post_webhook):
    # transcript arrives before call.started
    post_webhook(make_event("e2", "transcript.chunk", timestamp="2026-01-10T10:00:09Z", text="hi"))
    call = Call.objects.get(provider_call_id="call_1")
    assert call.started_at.isoformat() == "2026-01-10T10:00:09+00:00"

    post_webhook(make_event("e1", "call.started", timestamp="2026-01-10T10:00:00Z", agent_id="a1"))
    call.refresh_from_db()
    assert call.started_at.isoformat() == "2026-01-10T10:00:00+00:00"
    assert call.agent_id == "a1"


def test_error_end_reason_marks_call_failed(post_webhook):
    post_webhook(make_event("e1", "call.ended", duration_seconds=3, end_reason="error", usage={}))
    call = Call.objects.get(provider_call_id="call_1")
    assert call.status == Call.Status.FAILED
    assert call.started_at is not None


def test_invalid_payload_returns_400(post_webhook):
    response = post_webhook({"event_id": "e1", "type": "not.a.type", "call_id": "c", "timestamp": "nope"})
    assert response.status_code == 400
    assert "type" in response.json()
    assert not CallEvent.objects.exists()
