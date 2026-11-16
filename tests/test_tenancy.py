"""One organization must never see or touch another organization's data."""
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import Membership
from calls.models import Call, CallEvent
from tests.conftest import make_event, signed_webhook, user_client

pytestmark = pytest.mark.django_db


def create_call(org, call_id, **extra):
    return Call.objects.create(organization=org, provider_call_id=call_id, started_at=timezone.now(), **extra)


@pytest.fixture
def two_orgs(tenant, other_tenant):
    create_call(tenant.org, "acme-call", agent_id="acme-bot")
    create_call(other_tenant.org, "globex-call", agent_id="globex-bot")
    return tenant, other_tenant


@pytest.mark.parametrize("client_kind", ["jwt", "api_key"])
def test_list_only_shows_own_calls(two_orgs, client_kind):
    acme, globex = two_orgs
    for tenant, expected in ((acme, ["acme-call"]), (globex, ["globex-call"])):
        client = tenant.client() if client_kind == "jwt" else tenant.key_client()
        ids = [row["id"] for row in client.get("/api/calls/").json()["results"]]
        assert ids == expected


def test_detail_of_another_orgs_call_is_404(two_orgs):
    acme, _ = two_orgs
    assert acme.client().get("/api/calls/acme-call/").status_code == 200
    # 404 rather than 403, so the response does not reveal the id exists.
    assert acme.client().get("/api/calls/globex-call/").status_code == 404
    assert acme.key_client().get("/api/calls/globex-call/").status_code == 404


def test_stats_only_count_own_calls(two_orgs):
    acme, globex = two_orgs
    create_call(globex.org, "globex-2")
    window = {"days": 1}
    assert acme.client().get("/api/stats/", window).json()["totals"]["calls"] == 1
    assert globex.client().get("/api/stats/", window).json()["totals"]["calls"] == 2


def test_user_cannot_pick_an_org_they_do_not_belong_to(two_orgs):
    acme, globex = two_orgs
    response = user_client(acme.owner, org=globex.org).get("/api/calls/")
    assert response.status_code == 403
    assert "not a member" in response.json()["detail"]


def test_org_header_switches_between_the_users_orgs(two_orgs):
    acme, globex = two_orgs
    Membership.objects.create(user=acme.owner, organization=globex.org, role=Membership.Role.MEMBER)

    def ids(org):
        return [r["id"] for r in user_client(acme.owner, org=org).get("/api/calls/").json()["results"]]

    assert ids(acme.org) == ["acme-call"]
    assert ids(globex.org) == ["globex-call"]


def test_without_header_the_oldest_membership_is_used(two_orgs):
    acme, _ = two_orgs
    response = user_client(acme.owner).get("/api/calls/")
    assert [r["id"] for r in response.json()["results"]] == ["acme-call"]


def test_api_key_ignores_the_org_header(two_orgs):
    # A key belongs to one org; a header cannot redirect it elsewhere.
    acme, globex = two_orgs
    client = acme.key_client()
    response = client.get("/api/calls/", HTTP_X_ORGANIZATION=globex.org.slug)
    assert [r["id"] for r in response.json()["results"]] == ["acme-call"]


def test_same_ids_in_two_orgs_do_not_collide(tenant, other_tenant, api_client):
    payload = make_event("evt_1", "call.started", call_id="shared-id", agent_id="bot")

    for t in (tenant, other_tenant):
        response = signed_webhook(api_client, payload, t.api_key, t.org.webhook_secret)
        assert response.status_code == 202  # not "duplicate": the ids are per org

    assert Call.objects.filter(provider_call_id="shared-id").count() == 2
    assert CallEvent.objects.filter(event_id="evt_1").count() == 2
    assert set(CallEvent.objects.values_list("organization", flat=True)) == {tenant.org.pk, other_tenant.org.pk}


def test_webhook_must_be_signed_with_the_keys_own_org_secret(tenant, other_tenant, api_client):
    payload = make_event("evt_1", "call.started")
    response = signed_webhook(api_client, payload, tenant.api_key, other_tenant.org.webhook_secret)
    assert response.status_code == 401
    assert not Call.objects.exists()


def test_webhook_lands_in_the_api_keys_org(tenant, other_tenant, api_client):
    payload = make_event("evt_1", "call.started", call_id="c-globex")
    signed_webhook(api_client, payload, other_tenant.api_key, other_tenant.org.webhook_secret)
    assert Call.objects.get(provider_call_id="c-globex").organization == other_tenant.org


def test_rotated_secret_keeps_working_during_the_grace_period(tenant, post_webhook):
    old_secret = tenant.org.webhook_secret
    tenant.org.rotate_webhook_secret(grace=timedelta(hours=1))

    assert post_webhook(make_event("e1", "call.started"), secret=old_secret).status_code == 202
    assert post_webhook(make_event("e2", "call.started"), secret=tenant.org.webhook_secret).status_code == 202

    tenant.org.previous_secret_expires_at = timezone.now() - timedelta(seconds=1)
    tenant.org.save()
    assert post_webhook(make_event("e3", "call.started"), secret=old_secret).status_code == 401
