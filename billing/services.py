"""Plans, metering and limit checks. Everything else asks this module, so the
rules for "is this org allowed to do X" live in one place."""
import math
from datetime import date

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Plan, Subscription, UsageCounter


class PlanLimitExceeded(APIException):
    """402: the request is valid, but the plan does not allow it. Upgrading fixes it.

    Rate limiting (too many requests per minute) is a separate 429.
    """

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "plan_limit_exceeded"

    def __init__(self, plan, limit, used, allowed, message):
        super().__init__(message)
        # Set directly: APIException would turn the numbers into strings.
        self.detail = {
            "detail": message,
            "code": self.default_code,
            "limit": limit,
            "plan": plan.code,
            "used": used,
            "allowed": allowed,
        }


def current_period(now=None):
    now = now or timezone.now()
    return date(now.year, now.month, 1)


def get_subscription(org):
    try:
        return org.subscription
    except Subscription.DoesNotExist:
        default_plan = Plan.objects.get(code=settings.DEFAULT_PLAN_CODE)
        subscription, _ = Subscription.objects.get_or_create(organization=org, defaults={"plan": default_plan})
        org.subscription = subscription
        return subscription


def get_plan(org):
    return get_subscription(org).plan


def get_usage(org, period=None):
    """This month's counter. Not saved until something is recorded."""
    period = period or current_period()
    return UsageCounter.objects.filter(organization=org, period=period).first() or UsageCounter(
        organization=org, period=period
    )


def _increment(org, **fields):
    counter, _ = UsageCounter.objects.get_or_create(organization=org, period=current_period())
    # F() makes the database do the addition, so concurrent requests never
    # overwrite each other's increments.
    UsageCounter.objects.filter(pk=counter.pk).update(**{name: F(name) + n for name, n in fields.items()})


def record_call_started(org):
    _increment(org, calls=1)


def record_call_minutes(org, duration_seconds):
    minutes = math.ceil(duration_seconds / 60) if duration_seconds > 0 else 0
    if minutes:
        _increment(org, billed_minutes=minutes)


def check_can_start_call(org):
    """Raise PlanLimitExceeded if a new call would go over this month's plan.

    Only new calls are refused. Events for a call that already started are
    still accepted, so a call is never cut off half way through.
    """
    plan = get_plan(org)
    usage = get_usage(org)
    if plan.monthly_call_limit is not None and usage.calls >= plan.monthly_call_limit:
        raise PlanLimitExceeded(
            plan, "monthly_calls", usage.calls, plan.monthly_call_limit,
            f"The {plan.name} plan includes {plan.monthly_call_limit} calls per month and this month's are used up. "
            "Upgrade the plan to keep ingesting new calls.",
        )
    if plan.monthly_minute_limit is not None and usage.billed_minutes >= plan.monthly_minute_limit:
        raise PlanLimitExceeded(
            plan, "monthly_minutes", usage.billed_minutes, plan.monthly_minute_limit,
            f"The {plan.name} plan includes {plan.monthly_minute_limit} call minutes per month and they are used up. "
            "Upgrade the plan to keep ingesting new calls.",
        )


RESOURCE_LIMITS = {
    "api_keys": ("max_api_keys", "API keys"),
    "webhook_endpoints": ("max_webhook_endpoints", "webhook endpoints"),
}


def check_resource_limit(org, resource, current_count):
    """Raise PlanLimitExceeded if the org already has as many `resource` as allowed."""
    field, label = RESOURCE_LIMITS[resource]
    plan = get_plan(org)
    allowed = getattr(plan, field)
    if allowed is not None and current_count >= allowed:
        raise PlanLimitExceeded(
            plan, resource, current_count, allowed,
            f"The {plan.name} plan allows {allowed} {label}. Revoke one or upgrade the plan.",
        )


def apply_plan(subscription, plan, status=Subscription.Status.ACTIVE):
    """The single place a plan change is written.

    The fake provider calls this directly. A real provider would call it from
    its payment webhook once the payment has gone through.
    """
    subscription.plan = plan
    subscription.status = status
    subscription.save(update_fields=["plan", "status", "updated_at"])
    return subscription
