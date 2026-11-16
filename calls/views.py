import json
import logging

from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import CallFilter
from .models import Call
from .serializers import CallDetailSerializer, CallListSerializer, WebhookEventSerializer
from .services import ingest_event
from .signatures import SignatureError, verify_signature
from .stats import build_stats

logger = logging.getLogger(__name__)


class CallWebhookView(APIView):
    """Receives call events from the telephony provider."""

    # Webhooks authenticate with the HMAC signature, not the read API key.
    permission_classes = [AllowAny]

    def post(self, request):
        raw_body = request.body  # verify the exact bytes that were signed
        try:
            verify_signature(
                secret=settings.WEBHOOK_SECRET,
                timestamp=request.headers.get("X-Webhook-Timestamp"),
                signature=request.headers.get("X-Webhook-Signature"),
                body=raw_body,
                tolerance=settings.WEBHOOK_TOLERANCE_SECONDS,
            )
        except SignatureError as exc:
            logger.warning("rejected webhook: %s", exc)
            return Response({"detail": "invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            body = json.loads(raw_body)
        except ValueError:
            return Response({"detail": "body must be JSON"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = WebhookEventSerializer(data=body)
        serializer.is_valid(raise_exception=True)

        event, created = ingest_event(serializer.validated_data)
        if not created:
            # Tell the provider it worked so it stops retrying.
            return Response({"status": "duplicate"}, status=status.HTTP_200_OK)
        return Response({"status": "accepted", "event_id": event.event_id}, status=status.HTTP_202_ACCEPTED)


class CallListView(generics.ListAPIView):
    queryset = Call.objects.all()
    serializer_class = CallListSerializer
    filterset_class = CallFilter
    search_fields = ["provider_call_id", "from_number", "to_number"]
    ordering_fields = ["started_at", "duration_seconds", "cost_usd"]
    ordering = ["-started_at"]


class CallDetailView(generics.RetrieveAPIView):
    queryset = Call.objects.prefetch_related("events")
    serializer_class = CallDetailSerializer
    lookup_field = "provider_call_id"
    lookup_url_kwarg = "call_id"


class StatsView(APIView):
    def get(self, request):
        try:
            days = int(request.query_params.get("days", 14))
        except ValueError:
            return Response({"detail": "days must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        days = max(1, min(days, 90))
        return Response(build_stats(days=days))


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})
