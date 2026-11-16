from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import ApiKey, Membership, hash_api_key

pytestmark = pytest.mark.django_db


def test_created_key_is_shown_once_and_stored_hashed(tenant):
    client = tenant.client()
    response = client.post("/api/api-keys/", {"name": "prod ingest"}, format="json")

    assert response.status_code == 201
    raw = response.json()["key"]
    assert raw.startswith(response.json()["prefix"] + "_")

    stored = ApiKey.objects.get(pk=response.json()["id"])
    assert stored.key_hash == hash_api_key(raw)
    assert raw not in (stored.key_hash, stored.prefix)

    listed = client.get("/api/api-keys/").json()
    assert {k["name"] for k in listed} == {"test", "prod ingest"}
    assert all("key" not in k and "key_hash" not in k for k in listed)


def test_new_key_authenticates(tenant, api_client):
    raw = tenant.client().post("/api/api-keys/", {"name": "k"}, format="json").json()["key"]
    assert api_client.get("/api/calls/", HTTP_X_API_KEY=raw).status_code == 200


@pytest.mark.parametrize("bad_key", ["nope", "cf_deadbeef_wrong", "cf__", ""])
def test_unknown_or_malformed_keys_are_rejected(api_client, tenant, bad_key):
    response = api_client.get("/api/calls/", HTTP_X_API_KEY=bad_key)
    assert response.status_code == 401


def test_right_prefix_wrong_secret_is_rejected(tenant, api_client):
    prefix = tenant.api_key.rsplit("_", 1)[0]
    response = api_client.get("/api/calls/", HTTP_X_API_KEY=prefix + "_" + "0" * 40)
    assert response.status_code == 401


def test_revoked_key_stops_working(tenant):
    key = ApiKey.objects.get(organization=tenant.org)
    assert tenant.key_client().get("/api/calls/").status_code == 200

    response = tenant.client().delete(f"/api/api-keys/{key.pk}/")

    assert response.status_code == 204
    key.refresh_from_db()
    assert key.revoked_at is not None  # kept for history, not deleted
    assert tenant.key_client().get("/api/calls/").status_code == 401


def test_members_cannot_manage_keys(tenant):
    member = tenant.add_user("member@acme.test")
    client = tenant.client(member)
    assert client.get("/api/api-keys/").status_code == 403
    assert client.post("/api/api-keys/", {"name": "x"}, format="json").status_code == 403


def test_admins_can_manage_keys(tenant):
    admin = tenant.add_user("admin@acme.test", role=Membership.Role.ADMIN)
    assert tenant.client(admin).post("/api/api-keys/", {"name": "x"}, format="json").status_code == 201


def test_api_key_cannot_manage_keys(tenant):
    # A leaked ingest key must not be able to mint more keys.
    client = tenant.key_client()
    assert client.get("/api/api-keys/").status_code == 403
    assert client.post("/api/api-keys/", {"name": "x"}, format="json").status_code == 403


def test_cannot_revoke_another_orgs_key(tenant, other_tenant):
    their_key = ApiKey.objects.get(organization=other_tenant.org)
    assert tenant.client().delete(f"/api/api-keys/{their_key.pk}/").status_code == 404
    their_key.refresh_from_db()
    assert their_key.revoked_at is None


def test_last_used_is_recorded_but_not_on_every_request(tenant):
    key = ApiKey.objects.get(organization=tenant.org)
    tenant.key_client().get("/api/calls/")
    key.refresh_from_db()
    first = key.last_used_at
    assert first is not None

    tenant.key_client().get("/api/calls/")
    key.refresh_from_db()
    assert key.last_used_at == first  # within a minute: no extra write

    key.mark_used(now=first + timedelta(minutes=2))
    key.refresh_from_db()
    assert key.last_used_at == first + timedelta(minutes=2)


def test_webhook_secret_view_and_rotation(tenant):
    client = tenant.client()
    old = client.get("/api/orgs/current/webhook-secret/").json()["webhook_secret"]
    assert old == tenant.org.webhook_secret

    rotated = client.post("/api/orgs/current/webhook-secret/").json()

    assert rotated["webhook_secret"] != old
    assert rotated["webhook_secret"].startswith("whsec_")
    tenant.org.refresh_from_db()
    assert tenant.org.active_webhook_secrets() == [rotated["webhook_secret"], old]
    assert tenant.org.previous_secret_expires_at > timezone.now() + timedelta(hours=23)


def test_members_cannot_read_the_webhook_secret(tenant):
    member = tenant.add_user("member@acme.test")
    assert tenant.client(member).get("/api/orgs/current/webhook-secret/").status_code == 403
