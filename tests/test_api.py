from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from calls.models import Call, CallEvent
from calls.stats import build_stats

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)


def create_call(org, call_id, days_ago=0, duration=60, cost="0.10", status=Call.Status.COMPLETED, **extra):
    started = NOW - timedelta(days=days_ago, hours=1)
    return Call.objects.create(
        organization=org,
        provider_call_id=call_id,
        started_at=started,
        ended_at=started + timedelta(seconds=duration),
        duration_seconds=duration,
        cost_usd=Decimal(cost),
        status=status,
        **extra,
    )


@pytest.fixture
def org(tenant):
    return tenant.org


@pytest.fixture
def api_client(tenant):
    # Read endpoints accept both auth methods; these tests use the dashboard one.
    return tenant.client()


def test_list_calls_is_paginated_and_newest_first(api_client, org):
    for i in range(25):
        create_call(org, f"c{i}", days_ago=i % 5)

    response = api_client.get("/api/calls/")
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 25
    assert len(body["results"]) == 20
    assert body["next"] is not None
    started = [row["started_at"] for row in body["results"]]
    assert started == sorted(started, reverse=True)


def test_list_calls_filters(api_client, org):
    create_call(org, "a", agent_id="sales", duration=30)
    create_call(org, "b", agent_id="support", duration=300)
    create_call(org, "c", agent_id="support", duration=10, status=Call.Status.FAILED)

    def ids(query):
        return sorted(row["id"] for row in api_client.get(f"/api/calls/?{query}").json()["results"])

    assert ids("agent_id=support") == ["b", "c"]
    assert ids("status=failed") == ["c"]
    assert ids("min_duration=60") == ["b"]
    assert ids("search=a") == ["a"]


def test_call_detail_includes_timeline(api_client, org):
    call = create_call(org, "c1")
    CallEvent.objects.create(organization=org, call=call, event_id="e2", type="call.ended", occurred_at=NOW)
    CallEvent.objects.create(
        organization=org, call=call, event_id="e1", type="call.started", occurred_at=NOW - timedelta(minutes=1)
    )

    response = api_client.get("/api/calls/c1/")

    assert response.status_code == 200
    assert [e["event_id"] for e in response.json()["events"]] == ["e1", "e2"]


def test_call_detail_404(api_client):
    assert api_client.get("/api/calls/missing/").status_code == 404


def test_read_api_also_accepts_the_org_api_key(tenant, org):
    create_call(org, "c1")
    response = tenant.key_client().get("/api/calls/")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_stats_aggregates_per_day(org):
    create_call(org, "today-1", days_ago=0, duration=60, cost="0.10", outcome_tags=["resolved"])
    create_call(org, "today-2", days_ago=0, duration=120, cost="0.30", outcome_tags=["resolved", "tool_used"])
    create_call(org, "two-days", days_ago=2, duration=30, cost="0.05", status=Call.Status.FAILED)
    create_call(org, "too-old", days_ago=30)

    stats = build_stats(org, days=7, now=NOW)

    assert stats["totals"]["calls"] == 3
    assert stats["totals"]["completed"] == 2
    assert stats["totals"]["failed"] == 1
    assert stats["totals"]["avg_duration"] == 70.0
    assert stats["totals"]["total_cost_usd"] == 0.45
    assert len(stats["per_day"]) == 7

    by_date = {row["date"]: row for row in stats["per_day"]}
    assert by_date["2026-01-15"] == {"date": "2026-01-15", "calls": 2, "avg_duration": 90.0, "cost_usd": 0.4}
    assert by_date["2026-01-13"]["calls"] == 1
    assert by_date["2026-01-14"]["calls"] == 0  # gaps are filled with zeros
    assert stats["outcome_tags"] == {"resolved": 2, "tool_used": 1}


def test_stats_endpoint_validates_days(api_client):
    assert api_client.get("/api/stats/?days=abc").status_code == 400
    assert api_client.get("/api/stats/?days=500").json()["range"]["days"] == 90
