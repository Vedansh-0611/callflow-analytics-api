import pytest

from billing import services
from billing.models import Plan, UsageCounter
from billing.providers import FakeBillingProvider
from tests.conftest import full_call, make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def tiny_plan(tenant):
    """Put the tenant on a plan small enough to hit in a test."""
    plan = Plan.objects.create(
        code="tiny", name="Tiny", monthly_call_limit=2, monthly_minute_limit=100,
        api_requests_per_minute=1000, max_api_keys=2, max_webhook_endpoints=1,
    )
    services.apply_plan(services.get_subscription(tenant.org), plan)
    return plan


def test_new_orgs_start_on_free(tenant):
    plan = services.get_plan(tenant.org)
    assert plan.code == "free"
    assert plan.monthly_call_limit == 500


def test_calls_and_minutes_are_metered(tenant, post_webhook):
    for payload in full_call("a", duration=61) + full_call("b", duration=30):
        post_webhook(payload)

    usage = services.get_usage(tenant.org)
    assert usage.calls == 2
    assert usage.billed_minutes == 3  # 61s -> 2 minutes, 30s -> 1 minute


def test_retried_and_repeated_events_are_not_metered_twice(tenant, post_webhook):
    events = full_call("a", duration=61)
    for payload in events + events:
        post_webhook(payload)
    # A second, different call.ended for the same call does not add minutes either.
    post_webhook(make_event("a_6", "call.ended", "a", duration_seconds=600, usage={}))

    usage = services.get_usage(tenant.org)
    assert (usage.calls, usage.billed_minutes) == (1, 2)


def test_call_limit_returns_402_with_a_clear_error(tiny_plan, post_webhook):
    assert post_webhook(make_event("e1", "call.started", "c1")).status_code == 202
    assert post_webhook(make_event("e2", "call.started", "c2")).status_code == 202

    response = post_webhook(make_event("e3", "call.started", "c3"))

    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "plan_limit_exceeded"
    assert body["limit"] == "monthly_calls"
    assert (body["plan"], body["used"], body["allowed"]) == ("tiny", 2, 2)
    assert "Upgrade" in body["detail"]


def test_calls_in_progress_can_finish_after_the_limit(tiny_plan, post_webhook):
    post_webhook(make_event("e1", "call.started", "c1"))
    post_webhook(make_event("e2", "call.started", "c2"))

    # c1 already started, so its later events are still accepted.
    assert post_webhook(make_event("e3", "transcript.chunk", "c1", text="hi")).status_code == 202
    assert post_webhook(make_event("e4", "call.ended", "c1", duration_seconds=30, usage={})).status_code == 202
    # A retry of an accepted event is still a 200 duplicate, not a 402.
    assert post_webhook(make_event("e1", "call.started", "c1")).status_code == 200


def test_minute_limit_blocks_new_calls(tiny_plan, tenant, post_webhook):
    UsageCounter.objects.create(organization=tenant.org, period=services.current_period(), calls=0, billed_minutes=100)
    response = post_webhook(make_event("e1", "call.started", "c1"))
    assert response.status_code == 402
    assert response.json()["limit"] == "monthly_minutes"


def test_upgrading_lifts_the_limit(tiny_plan, tenant, post_webhook):
    post_webhook(make_event("e1", "call.started", "c1"))
    post_webhook(make_event("e2", "call.started", "c2"))
    assert post_webhook(make_event("e3", "call.started", "c3")).status_code == 402

    response = tenant.client().post("/api/billing/change-plan/", {"plan": "pro"}, format="json")

    assert response.status_code == 200
    assert response.json()["result"] == {"status": "active", "plan": "pro", "redirect_url": None}
    assert response.json()["plan"]["code"] == "pro"
    assert post_webhook(make_event("e3", "call.started", "c3")).status_code == 202


def test_api_key_count_is_limited_by_plan(tiny_plan, tenant):
    client = tenant.client()
    assert client.post("/api/api-keys/", {"name": "second"}, format="json").status_code == 201

    response = client.post("/api/api-keys/", {"name": "third"}, format="json")

    assert response.status_code == 402
    assert response.json()["limit"] == "api_keys"


def test_rate_limit_comes_from_the_plan(tiny_plan, tenant):
    tiny_plan.api_requests_per_minute = 2
    tiny_plan.save()
    client = tenant.key_client()
    assert [client.get("/api/calls/").status_code for _ in range(3)] == [200, 200, 429]


def test_billing_overview(tenant, post_webhook):
    post_webhook(make_event("e1", "call.started", "c1"))
    member = tenant.add_user("m@acme.test")

    body = tenant.client(member).get("/api/billing/").json()

    assert body["plan"]["code"] == "free"
    assert body["usage"]["calls"] == 1
    assert [p["code"] for p in body["plans"]] == ["free", "pro"]


def test_only_admins_change_plans(tenant):
    member = tenant.add_user("m@acme.test")
    response = tenant.client(member).post("/api/billing/change-plan/", {"plan": "pro"}, format="json")
    assert response.status_code == 403
    assert tenant.key_client().post("/api/billing/change-plan/", {"plan": "pro"}, format="json").status_code == 403


def test_unknown_plan_is_400(tenant):
    response = tenant.client().post("/api/billing/change-plan/", {"plan": "platinum"}, format="json")
    assert response.status_code == 400


def test_fake_provider_cancel_goes_back_to_free(tenant):
    subscription = services.get_subscription(tenant.org)
    services.apply_plan(subscription, Plan.objects.get(code="pro"))
    FakeBillingProvider().cancel(subscription)
    assert services.get_plan(tenant.org).code == "free"


def test_usage_is_per_org(tenant, other_tenant, post_webhook):
    post_webhook(make_event("e1", "call.started", "c1"))
    assert services.get_usage(tenant.org).calls == 1
    assert services.get_usage(other_tenant.org).calls == 0
