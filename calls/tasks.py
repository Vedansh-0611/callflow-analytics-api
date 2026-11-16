import logging

from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from outbound.services import dispatch_event

from .models import Call, CallEvent
from .outcomes import derive_outcome_tags
from .pricing import calculate_cost
from .serializers import CallListSerializer

logger = logging.getLogger(__name__)


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True, max_retries=3)
def summarize_call(call_pk):
    """Compute cost, counters and outcome tags for a finished call.

    Safe to run more than once: it always recomputes from stored data.
    """
    call = Call.objects.select_related("organization").get(pk=call_pk)
    events = list(call.events.all())
    first_summary = call.summarized_at is None

    call.cost_usd = calculate_cost(
        model=call.llm_model,
        prompt_tokens=call.prompt_tokens,
        completion_tokens=call.completion_tokens,
        duration_seconds=call.duration_seconds,
    )
    call.transcript_turns = sum(1 for e in events if e.type == CallEvent.Type.TRANSCRIPT_CHUNK)
    call.tool_calls = sum(1 for e in events if e.type == CallEvent.Type.TOOL_CALLED)
    call.outcome_tags = derive_outcome_tags(call, events)
    call.summarized_at = timezone.now()
    call.save(
        update_fields=[
            "cost_usd",
            "transcript_turns",
            "tool_calls",
            "outcome_tags",
            "summarized_at",
            "updated_at",
        ]
    )
    logger.info("summarized call %s cost=%s tags=%s", call.provider_call_id, call.cost_usd, call.outcome_tags)

    if first_summary:
        # Re-running the task (it is idempotent) must not notify customers again.
        # dispatch_event is idempotent on the event id as a second safeguard.
        dispatch_event(
            call.organization,
            "call.summarized",
            event_id=f"call.summarized.{call.provider_call_id}",
            data=CallListSerializer(call).data,
        )
    return {"call": call.provider_call_id, "cost_usd": str(call.cost_usd), "tags": call.outcome_tags}
