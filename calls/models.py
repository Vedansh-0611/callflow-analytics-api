from django.db import models


class Call(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="calls")
    # The id the telephony provider uses. Every webhook references it. Unique per
    # organization, since two customers' providers can reuse the same ids.
    provider_call_id = models.CharField(max_length=64)
    agent_id = models.CharField(max_length=64, blank=True, default="")
    direction = models.CharField(max_length=16, choices=Direction.choices, blank=True, default="")
    from_number = models.CharField(max_length=32, blank=True, default="")
    to_number = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    end_reason = models.CharField(max_length=32, blank=True, default="")

    # Usage reported by the provider in the call.ended event.
    llm_model = models.CharField(max_length=64, blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)

    # Filled in by the summarize_call Celery task.
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    outcome_tags = models.JSONField(default=list, blank=True)
    transcript_turns = models.PositiveIntegerField(default=0)
    tool_calls = models.PositiveIntegerField(default=0)
    summarized_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "provider_call_id"], name="unique_call_per_org"),
        ]
        # Every query is filtered by organization first, so it leads each index.
        indexes = [
            # List view default ordering and the stats date range filter.
            models.Index(fields=["organization", "started_at"], name="call_org_started_idx"),
            # Common dashboard filters combined with the date range.
            models.Index(fields=["organization", "status", "started_at"], name="call_org_status_started_idx"),
            models.Index(fields=["organization", "agent_id", "started_at"], name="call_org_agent_started_idx"),
        ]

    def __str__(self):
        return self.provider_call_id

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens


class CallEvent(models.Model):
    class Type(models.TextChoices):
        CALL_STARTED = "call.started", "Call started"
        TRANSCRIPT_CHUNK = "transcript.chunk", "Transcript chunk"
        TOOL_CALLED = "tool.called", "Tool called"
        CALL_ENDED = "call.ended", "Call ended"

    # Denormalized from the call so the idempotency constraint can be per org.
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="+")
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="events")
    # Unique id sent by the provider. The unique constraint is what makes
    # webhook retries safe: the same event can never be stored twice.
    event_id = models.CharField(max_length=64)
    type = models.CharField(max_length=32, choices=Type.choices)
    occurred_at = models.DateTimeField()
    data = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "event_id"], name="unique_event_per_org"),
        ]
        indexes = [
            # Timeline query: all events of one call in time order.
            models.Index(fields=["call", "occurred_at"], name="event_call_time_idx"),
        ]

    def __str__(self):
        return f"{self.type} ({self.event_id})"
