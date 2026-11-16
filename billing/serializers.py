from rest_framework import serializers

from .models import Plan, UsageCounter


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "code",
            "name",
            "price_cents_per_month",
            "monthly_call_limit",
            "monthly_minute_limit",
            "api_requests_per_minute",
            "max_api_keys",
            "max_webhook_endpoints",
        ]


class UsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageCounter
        fields = ["period", "calls", "billed_minutes"]


class ChangePlanSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(slug_field="code", queryset=Plan.objects.all())


class ChangePlanResultSerializer(serializers.Serializer):
    status = serializers.CharField()
    plan = serializers.CharField()
    redirect_url = serializers.URLField(allow_null=True)


class BillingOverviewSerializer(serializers.Serializer):
    plan = PlanSerializer()
    status = serializers.CharField()
    usage = UsageSerializer()
    history = UsageSerializer(many=True)
    plans = PlanSerializer(many=True)


class ChangePlanResponseSerializer(BillingOverviewSerializer):
    result = ChangePlanResultSerializer()
