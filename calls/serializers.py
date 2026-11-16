from rest_framework import serializers

from .models import Call, CallEvent


class WebhookEventSerializer(serializers.Serializer):
    """Validates the incoming webhook body before we touch the database."""

    event_id = serializers.CharField(max_length=64)
    type = serializers.ChoiceField(choices=CallEvent.Type.choices)
    call_id = serializers.CharField(max_length=64)
    timestamp = serializers.DateTimeField()
    data = serializers.DictField(required=False, default=dict)


class CallEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallEvent
        fields = ["event_id", "type", "occurred_at", "data"]


class CallListSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="provider_call_id")
    cost_usd = serializers.DecimalField(max_digits=10, decimal_places=4, coerce_to_string=False)
    total_tokens = serializers.IntegerField(read_only=True)

    class Meta:
        model = Call
        fields = [
            "id",
            "agent_id",
            "direction",
            "from_number",
            "to_number",
            "status",
            "started_at",
            "ended_at",
            "duration_seconds",
            "end_reason",
            "llm_model",
            "total_tokens",
            "cost_usd",
            "outcome_tags",
        ]


class CallDetailSerializer(CallListSerializer):
    events = CallEventSerializer(many=True, read_only=True)

    class Meta(CallListSerializer.Meta):
        fields = CallListSerializer.Meta.fields + [
            "prompt_tokens",
            "completion_tokens",
            "transcript_turns",
            "tool_calls",
            "summarized_at",
            "events",
        ]
