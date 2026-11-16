"""Billing provider interface.

The app never talks to a payment company directly; it calls the provider set
in settings.BILLING_PROVIDER. Today that is FakeBillingProvider, which switches
plans instantly. Adding Stripe means writing one class, without touching views:

    class StripeBillingProvider(BillingProvider):
        name = "stripe"

        def change_plan(self, subscription, plan):
            # 1. Create (or reuse) a Stripe Customer, save its id on
            #    subscription.provider_customer_id.
            # 2. Create a Checkout Session for the plan's Stripe price.
            # 3. Return ChangePlanResult(status="pending", redirect_url=session.url).
            ...

    plus a webhook view at /api/billing/stripe/webhook/ that verifies the
    Stripe-Signature header and, on `checkout.session.completed` or
    `customer.subscription.updated`, looks up the Subscription by
    provider_subscription_id and calls services.apply_plan(). That webhook is
    the only place a paid plan is granted, so a user closing the checkout tab
    early never gets a free upgrade.
"""
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

from . import services


@dataclass
class ChangePlanResult:
    status: str  # "active": done now. "pending": waiting for the customer to pay.
    plan: str
    redirect_url: str | None = None


class BillingProvider:
    name = "base"

    def change_plan(self, subscription, plan) -> ChangePlanResult:
        raise NotImplementedError

    def cancel(self, subscription) -> None:
        raise NotImplementedError


class FakeBillingProvider(BillingProvider):
    """No payments: plan changes apply immediately. For development and demos."""

    name = "fake"

    def change_plan(self, subscription, plan):
        services.apply_plan(subscription, plan)
        return ChangePlanResult(status="active", plan=plan.code)

    def cancel(self, subscription):
        from .models import Plan

        services.apply_plan(subscription, Plan.objects.get(code=settings.DEFAULT_PLAN_CODE))


def get_billing_provider() -> BillingProvider:
    return import_string(settings.BILLING_PROVIDER)()
