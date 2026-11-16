import math
from decimal import Decimal

from django.conf import settings

ONE_MILLION = Decimal(1_000_000)


def get_model_price(model):
    table = settings.MODEL_PRICING
    return table.get(model) or table["default"]


def calculate_cost(model, prompt_tokens, completion_tokens, duration_seconds):
    """Total cost of one call in USD: LLM tokens plus per-minute telephony.

    Telephony is billed per started minute, which is how most carriers charge.
    Decimal is used throughout so we never accumulate float rounding errors.
    """
    price = get_model_price(model)
    llm_cost = (
        Decimal(prompt_tokens) * Decimal(str(price["input"]))
        + Decimal(completion_tokens) * Decimal(str(price["output"]))
    ) / ONE_MILLION

    billed_minutes = math.ceil(duration_seconds / 60) if duration_seconds > 0 else 0
    telephony_cost = Decimal(billed_minutes) * Decimal(str(settings.TELEPHONY_COST_PER_MINUTE))

    return (llm_cost + telephony_cost).quantize(Decimal("0.000001"))
