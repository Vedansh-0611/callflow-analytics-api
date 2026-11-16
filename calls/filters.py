import django_filters

from .models import Call


class CallFilter(django_filters.FilterSet):
    started_after = django_filters.IsoDateTimeFilter(field_name="started_at", lookup_expr="gte")
    started_before = django_filters.IsoDateTimeFilter(field_name="started_at", lookup_expr="lt")
    min_duration = django_filters.NumberFilter(field_name="duration_seconds", lookup_expr="gte")
    max_duration = django_filters.NumberFilter(field_name="duration_seconds", lookup_expr="lte")

    class Meta:
        model = Call
        fields = ["status", "agent_id", "direction", "end_reason"]
