from django.db import models


class Plan(models.Model):
    """What an organization may use per month. A null limit means unlimited."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    price_cents_per_month = models.PositiveIntegerField(default=0)

    monthly_call_limit = models.PositiveIntegerField(null=True, blank=True)
    monthly_minute_limit = models.PositiveIntegerField(null=True, blank=True)
    api_requests_per_minute = models.PositiveIntegerField(default=60)
    max_api_keys = models.PositiveIntegerField(null=True, blank=True)
    max_webhook_endpoints = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["price_cents_per_month"]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """Links an organization to its plan.

    The provider_* fields are where a real billing provider's ids go (for
    Stripe: the customer and subscription ids), so its webhooks can be
    matched back to the organization.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    organization = models.OneToOneField("accounts.Organization", on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    provider = models.CharField(max_length=32, default="fake")
    provider_customer_id = models.CharField(max_length=64, blank=True, default="")
    provider_subscription_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization} on {self.plan}"


class UsageCounter(models.Model):
    """Metered usage of one organization in one calendar month (UTC)."""

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="usage")
    period = models.DateField(help_text="First day of the month")
    calls = models.PositiveIntegerField(default=0)
    billed_minutes = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "period"], name="unique_usage_period"),
        ]

    def __str__(self):
        return f"{self.organization} {self.period:%Y-%m}: {self.calls} calls"
