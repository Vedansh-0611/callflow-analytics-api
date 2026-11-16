import secrets

from django.db import models


def generate_endpoint_secret():
    return "whsec_" + secrets.token_hex(24)


class WebhookEndpoint(models.Model):
    """A customer URL that receives events from us, e.g. call.summarized."""

    EVENT_TYPES = ["call.summarized"]

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    url = models.URLField(max_length=500)
    description = models.CharField(max_length=200, blank=True, default="")
    events = models.JSONField(default=list)
    # Used to sign what we send, so the receiver can check it came from us.
    secret = models.CharField(max_length=80, default=generate_endpoint_secret)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.url

    def rotate_secret(self):
        self.secret = generate_endpoint_secret()
        self.save(update_fields=["secret"])
        return self.secret


class WebhookDelivery(models.Model):
    """One event sent to one endpoint, with its retry history."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    # Stable per event: receivers use it to ignore duplicates, and the unique
    # constraint stops us from queueing the same event twice for an endpoint.
    event_id = models.CharField(max_length=80)
    event_type = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")
    next_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["endpoint", "event_id"], name="unique_delivery_per_endpoint"),
        ]

    def __str__(self):
        return f"{self.event_type} -> {self.endpoint} ({self.status})"
