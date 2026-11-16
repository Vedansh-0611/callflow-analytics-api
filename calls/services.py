"""Webhook ingestion: store the event once and update the call it belongs to."""
from datetime import timedelta

from django.db import IntegrityError, transaction

from .models import Call, CallEvent
from .tasks import summarize_call


def ingest_event(payload):
    """Store one validated webhook event.

    Returns (event, created). created is False when the event_id was already
    stored, which happens when the provider retries a delivery.
    """
    try:
        with transaction.atomic():
            call, _ = Call.objects.get_or_create(provider_call_id=payload["call_id"])
            # Lock the call row so two events for the same call update it one at a time.
            call = Call.objects.select_for_update().get(pk=call.pk)

            if CallEvent.objects.filter(event_id=payload["event_id"]).exists():
                return None, False

            event = CallEvent.objects.create(
                call=call,
                event_id=payload["event_id"],
                type=payload["type"],
                occurred_at=payload["timestamp"],
                data=payload.get("data") or {},
            )
            apply_event(call, event)

            if event.type == CallEvent.Type.CALL_ENDED:
                # Only enqueue after the commit, so the worker sees the saved data.
                transaction.on_commit(lambda: summarize_call.delay(call.pk))
    except IntegrityError:
        # Two deliveries of the same event raced; the unique constraint caught it.
        return None, False

    return event, True


def apply_event(call, event):
    data = event.data

    if event.type == CallEvent.Type.CALL_STARTED:
        call.started_at = event.occurred_at
        call.agent_id = data.get("agent_id", call.agent_id)
        call.direction = data.get("direction", call.direction)
        call.from_number = data.get("from", call.from_number)
        call.to_number = data.get("to", call.to_number)

    elif event.type == CallEvent.Type.CALL_ENDED:
        usage = data.get("usage") or {}
        call.ended_at = event.occurred_at
        call.duration_seconds = int(data.get("duration_seconds") or 0)
        call.end_reason = data.get("end_reason", "")
        call.llm_model = usage.get("model", "")
        call.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        call.completion_tokens = int(usage.get("completion_tokens") or 0)
        call.status = Call.Status.FAILED if call.end_reason == "error" else Call.Status.COMPLETED
        if call.started_at is None:
            # call.started never arrived (or arrives later); estimate it.
            call.started_at = event.occurred_at - timedelta(seconds=call.duration_seconds)

    elif call.started_at is None:
        # Events can arrive out of order. Use the first one we see as a placeholder.
        call.started_at = event.occurred_at

    call.save()
