import json

import pytest

from tests.conftest import make_event, make_tenant

pytestmark = pytest.mark.django_db


def test_api_key_is_rate_limited(tenant, settings):
    settings.API_KEY_THROTTLE_RATE = "3/min"
    client = tenant.key_client()

    statuses = [client.get("/api/calls/").status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    response = client.get("/api/calls/")
    assert int(response["Retry-After"]) > 0


def test_each_api_key_has_its_own_budget(tenant, settings):
    settings.API_KEY_THROTTLE_RATE = "2/min"
    other = make_tenant(name="Globex", email="o@globex.test")
    for _ in range(2):
        tenant.key_client().get("/api/calls/")

    assert tenant.key_client().get("/api/calls/").status_code == 429
    assert other.key_client().get("/api/calls/").status_code == 200


def test_webhooks_count_against_the_key_budget(tenant, post_webhook, settings):
    settings.API_KEY_THROTTLE_RATE = "2/min"
    assert post_webhook(make_event("e1", "call.started")).status_code == 202
    assert post_webhook(make_event("e2", "call.started")).status_code == 202
    assert post_webhook(make_event("e3", "call.started")).status_code == 429


def test_dashboard_users_are_not_limited_by_the_key_rate(tenant, settings):
    settings.API_KEY_THROTTLE_RATE = "1/min"
    client = tenant.client()
    assert [client.get("/api/calls/").status_code for _ in range(3)] == [200, 200, 200]


def test_login_is_rate_limited_per_ip(api_client, settings):
    settings.AUTH_THROTTLE_RATE = "2/min"
    attempt = {"email": "x@example.com", "password": "wrong-password"}
    statuses = [api_client.post("/api/auth/login/", attempt).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]


def test_oversized_webhook_is_rejected_with_413(tenant, post_webhook, settings):
    settings.WEBHOOK_MAX_BODY_BYTES = 200
    small = make_event("e1", "call.started")
    big = make_event("e2", "transcript.chunk", text="x" * 500)
    assert len(json.dumps(small)) < 200 < len(json.dumps(big))

    assert post_webhook(small).status_code == 202
    response = post_webhook(big)
    assert response.status_code == 413
    assert response.json()["detail"] == "Webhook body is larger than the allowed size."
