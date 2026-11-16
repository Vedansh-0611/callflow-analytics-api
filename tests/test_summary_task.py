from decimal import Decimal

import pytest

from calls.models import Call
from calls.pricing import calculate_cost
from calls.services import ingest_event
from calls.tasks import summarize_call
from tests.conftest import full_call


def test_cost_combines_tokens_and_telephony(settings):
    settings.MODEL_PRICING = {"m": {"input": 1.0, "output": 2.0}, "default": {"input": 0, "output": 0}}
    settings.TELEPHONY_COST_PER_MINUTE = "0.01"

    # 1M input tokens = $1, 500k output = $1, 61 seconds = 2 billed minutes = $0.02
    cost = calculate_cost("m", 1_000_000, 500_000, 61)
    assert cost == Decimal("2.020000")


def test_unknown_model_uses_default_price(settings):
    settings.MODEL_PRICING = {"default": {"input": 10.0, "output": 0}}
    settings.TELEPHONY_COST_PER_MINUTE = "0"
    assert calculate_cost("some-new-model", 100_000, 0, 0) == Decimal("1.000000")


def test_zero_duration_call_has_no_telephony_cost(settings):
    settings.TELEPHONY_COST_PER_MINUTE = "0.01"
    assert calculate_cost("gpt-4o-mini", 0, 0, 0) == Decimal("0")


@pytest.mark.django_db
def test_summarize_call_sets_cost_and_tags(settings):
    settings.TELEPHONY_COST_PER_MINUTE = "0.01"
    for payload in full_call(duration=125, tool_success=False):
        ingest_event(payload)
    call = Call.objects.get(provider_call_id="call_1")

    result = summarize_call(call.pk)

    call.refresh_from_db()
    # gpt-4o-mini: 2000 * 0.15/1M + 500 * 0.60/1M = 0.0006, plus 3 minutes * 0.01
    assert call.cost_usd == Decimal("0.030600")
    assert result["cost_usd"] == "0.030600"
    assert call.outcome_tags == ["tool_used", "tool_failed", "resolved"]


@pytest.mark.django_db
def test_summarize_is_idempotent():
    for payload in full_call():
        ingest_event(payload)
    call = Call.objects.get(provider_call_id="call_1")

    summarize_call(call.pk)
    first = Call.objects.get(pk=call.pk)
    summarize_call(call.pk)
    second = Call.objects.get(pk=call.pk)

    assert first.cost_usd == second.cost_usd
    assert first.outcome_tags == second.outcome_tags


@pytest.mark.django_db
@pytest.mark.parametrize(
    "duration,end_reason,expected",
    [
        (5, "voicemail", ["short_call", "voicemail", "tool_used", "booking_made"]),
        (200, "transferred", ["transferred", "tool_used", "booking_made"]),
        (90, "customer_hangup", ["customer_hung_up", "tool_used", "booking_made"]),
    ],
)
def test_outcome_tags(duration, end_reason, expected):
    for payload in full_call(duration=duration, end_reason=end_reason):
        ingest_event(payload)
    call = Call.objects.get(provider_call_id="call_1")
    summarize_call(call.pk)
    call.refresh_from_db()
    assert call.outcome_tags == expected
