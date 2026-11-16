from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.tenancy import IsOrgAdmin

from . import services
from .models import Plan
from .providers import get_billing_provider
from .serializers import (
    BillingOverviewSerializer,
    ChangePlanResponseSerializer,
    ChangePlanResultSerializer,
    ChangePlanSerializer,
    PlanSerializer,
    UsageSerializer,
)


def billing_overview(org):
    subscription = services.get_subscription(org)
    return {
        "plan": PlanSerializer(subscription.plan).data,
        "status": subscription.status,
        "usage": UsageSerializer(services.get_usage(org)).data,
        "history": UsageSerializer(org.usage.all()[:6], many=True).data,
        "plans": PlanSerializer(Plan.objects.all(), many=True).data,
    }


class BillingView(APIView):
    """The organization's plan, this month's usage and the plans it can switch to."""

    @extend_schema(responses=BillingOverviewSerializer, tags=["billing"])
    def get(self, request):
        return Response(billing_overview(request.organization))


class ChangePlanView(APIView):
    """Switch plans through the configured billing provider.

    With the fake provider the change is immediate. A real provider would
    return status "pending" and a checkout URL to send the user to.
    """

    permission_classes = [IsOrgAdmin]

    @extend_schema(request=ChangePlanSerializer, responses=ChangePlanResponseSerializer, tags=["billing"])
    def post(self, request):
        serializer = ChangePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subscription = services.get_subscription(request.organization)
        result = get_billing_provider().change_plan(subscription, serializer.validated_data["plan"])
        return Response(
            {"result": ChangePlanResultSerializer(asdict(result)).data, **billing_overview(request.organization)}
        )
