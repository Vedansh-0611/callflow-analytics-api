import pytest
from django.contrib.auth import get_user_model

from accounts.models import Membership, Organization
from tests.conftest import user_client

pytestmark = pytest.mark.django_db

SIGNUP = {
    "email": "Asha@Example.com",
    "password": "a-long-passphrase",
    "name": "Asha",
    "organization_name": "Asha Clinics",
}


def test_signup_creates_user_org_and_owner_membership(api_client):
    response = api_client.post("/api/auth/signup/", SIGNUP, format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == "asha@example.com"  # normalized
    assert body["user"]["organizations"] == [
        {"id": Organization.objects.get().pk, "name": "Asha Clinics", "slug": "asha-clinics", "role": "owner"}
    ]
    assert Membership.objects.get().role == Membership.Role.OWNER


def test_signup_rejects_duplicate_email_and_weak_password(api_client):
    api_client.post("/api/auth/signup/", SIGNUP, format="json")

    duplicate = api_client.post("/api/auth/signup/", {**SIGNUP, "email": "asha@example.com"}, format="json")
    weak = api_client.post(
        "/api/auth/signup/", {**SIGNUP, "email": "b@example.com", "password": "12345678"}, format="json"
    )

    assert duplicate.status_code == 400 and "email" in duplicate.json()
    assert weak.status_code == 400 and "password" in weak.json()


def test_org_slugs_stay_unique(api_client):
    api_client.post("/api/auth/signup/", SIGNUP, format="json")
    api_client.post("/api/auth/signup/", {**SIGNUP, "email": "other@example.com"}, format="json")
    slugs = sorted(Organization.objects.values_list("slug", flat=True))
    assert slugs[0] == "asha-clinics" and slugs[1].startswith("asha-clinics-")


def test_login_returns_tokens_that_work(api_client):
    api_client.post("/api/auth/signup/", SIGNUP, format="json")

    response = api_client.post("/api/auth/login/", {"email": "asha@example.com", "password": SIGNUP["password"]})
    assert response.status_code == 200

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    assert api_client.get("/api/calls/").status_code == 200
    assert api_client.get("/api/auth/me/").json()["email"] == "asha@example.com"


def test_login_with_wrong_password_is_401(api_client):
    api_client.post("/api/auth/signup/", SIGNUP, format="json")
    response = api_client.post("/api/auth/login/", {"email": "asha@example.com", "password": "nope-nope"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_refresh_token_gives_a_new_access_token(api_client):
    refresh = api_client.post("/api/auth/signup/", SIGNUP, format="json").json()["refresh"]
    response = api_client.post("/api/auth/refresh/", {"refresh": refresh})
    assert response.status_code == 200
    assert "access" in response.json()


@pytest.mark.parametrize("path", ["/api/calls/", "/api/stats/", "/api/orgs/current/", "/api/api-keys/"])
def test_tenant_endpoints_require_authentication(api_client, path):
    assert api_client.get(path).status_code == 401


def test_garbage_bearer_token_is_401(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")
    assert api_client.get("/api/calls/").status_code == 401


def test_user_can_create_a_second_org_and_owns_it(tenant):
    client = user_client(tenant.owner)
    response = client.post("/api/orgs/", {"name": "Side Project"}, format="json")

    assert response.status_code == 201
    orgs = client.get("/api/orgs/").json()
    assert [(o["name"], o["role"]) for o in orgs] == [("Acme", "owner"), ("Side Project", "owner")]


def test_current_org_lists_members_and_my_role(tenant):
    member = tenant.add_user("member@acme.test")
    body = tenant.client(member).get("/api/orgs/current/").json()
    assert body["slug"] == tenant.org.slug
    assert body["role"] == "member"
    assert {m["email"] for m in body["members"]} == {"owner@acme.test", "member@acme.test"}


def test_user_without_org_gets_a_clear_403(api_client):
    user = get_user_model().objects.create_user(username="lonely@x.test", password="pw-123456789")
    response = user_client(user).get("/api/calls/")
    assert response.status_code == 403
    assert "any organization" in response.json()["detail"]
