from rest_framework import serializers

from .models import WebhookDelivery, WebhookEndpoint
from .services import validate_endpoint_url


class WebhookEndpointSerializer(serializers.ModelSerializer):
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=WebhookEndpoint.EVENT_TYPES),
        allow_empty=False,
        default=lambda: list(WebhookEndpoint.EVENT_TYPES),
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["id", "url", "description", "events", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_url(self, value):
        error = validate_endpoint_url(value)
        if error:
            raise serializers.ValidationError(error)
        return value


class WebhookEndpointWithSecretSerializer(WebhookEndpointSerializer):
    """Returned on create and on secret rotation only."""

    secret = serializers.CharField(read_only=True)

    class Meta(WebhookEndpointSerializer.Meta):
        fields = WebhookEndpointSerializer.Meta.fields + ["secret"]


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            "id",
            "event_id",
            "event_type",
            "status",
            "attempts",
            "last_status_code",
            "last_error",
            "next_retry_at",
            "created_at",
            "delivered_at",
        ]
