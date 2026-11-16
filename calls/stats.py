from collections import Counter
from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Call


def _money(value):
    return round(float(value or 0), 4)


def build_stats(days=14, now=None):
    """Aggregate numbers for the dashboard over the last `days` days.

    Days without calls are filled with zeros so charts get a continuous axis.
    """
    now = now or timezone.now()
    first_day = (now - timedelta(days=days - 1)).date()
    calls = Call.objects.filter(started_at__date__gte=first_day, started_at__lte=now)

    totals = calls.aggregate(
        calls=Count("id"),
        avg_duration=Avg("duration_seconds"),
        total_cost=Sum("cost_usd"),
        total_tokens=Sum("prompt_tokens") + Sum("completion_tokens"),
    )

    rows = (
        calls.annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(calls=Count("id"), avg_duration=Avg("duration_seconds"), cost=Sum("cost_usd"))
        .order_by("day")
    )
    by_day = {row["day"]: row for row in rows}

    per_day = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        row = by_day.get(day, {})
        per_day.append(
            {
                "date": day.isoformat(),
                "calls": row.get("calls", 0),
                "avg_duration": round(row.get("avg_duration") or 0, 1),
                "cost_usd": _money(row.get("cost")),
            }
        )

    status_counts = dict(calls.order_by().values_list("status").annotate(n=Count("id")))

    # Tags live in a JSON list, so count them in Python. Fine for a 90-day
    # window; at larger scale they would move to their own indexed table.
    tag_counts = Counter(tag for tags in calls.values_list("outcome_tags", flat=True) for tag in tags)

    return {
        "range": {"from": first_day.isoformat(), "to": now.date().isoformat(), "days": days},
        "totals": {
            "calls": totals["calls"],
            "completed": status_counts.get(Call.Status.COMPLETED, 0),
            "failed": status_counts.get(Call.Status.FAILED, 0),
            "avg_duration": round(totals["avg_duration"] or 0, 1),
            "total_cost_usd": _money(totals["total_cost"]),
            "total_tokens": totals["total_tokens"] or 0,
        },
        "per_day": per_day,
        "outcome_tags": dict(tag_counts.most_common()),
    }
