import uuid

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.tenancy import IsOrgAdmin, OrgScopedQuerysetMixin
from billing import services as billing

from .models import WebhookDelivery, WebhookEndpoint
from .serializers import WebhookDeliverySerializer, WebhookEndpointSerializer, WebhookEndpointWithSecretSerializer
from .services import build_payload, enqueue


class WebhookEndpointViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    """Where we send events such as call.summarized. Owners and admins only."""

    permission_classes = [IsOrgAdmin]
    queryset = WebhookEndpoint.objects.all()
    serializer_class = WebhookEndpointSerializer
    pagination_class = None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = request.organization
        billing.check_resource_limit(org, "webhook_endpoints", WebhookEndpoint.objects.filter(organization=org).count())
        endpoint = serializer.save(organization=org)
        return Response(WebhookEndpointWithSecretSerializer(endpoint).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        endpoint = self.get_object()
        endpoint.rotate_secret()
        return Response(WebhookEndpointWithSecretSerializer(endpoint).data)

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        """Queue a `ping` event so the receiver can check its signature code."""
        endpoint = self.get_object()
        event_id = f"evt_ping_{uuid.uuid4().hex[:16]}"
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_id=event_id,
            event_type="ping",
            payload=build_payload(request.organization, "ping", event_id, {"message": "Hello from CallFlow"}),
        )
        enqueue(delivery)
        return Response(WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def deliveries(self, request, pk=None):
        """The 50 most recent deliveries to this endpoint."""
        endpoint = self.get_object()
        return Response(WebhookDeliverySerializer(endpoint.deliveries.all()[:50], many=True).data)
