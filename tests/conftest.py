import json
import time
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import ApiKey, Membership, Organization
from accounts.services import create_organization
from calls.signatures import compute_signature


@dataclass
class Tenant:
    """An organization with an owner and an API key, as most tests need."""

    org: Organization
    owner: object
    api_key: str

    def client(self, user=None):
        """A dashboard client: JWT for `user` (default the owner), acting in this org."""
        return user_client(user or self.owner, org=self.org)

    def key_client(self):
        """A server-to-server client using the org's API key."""
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=self.api_key)
        return client

    def add_user(self, email, role=Membership.Role.MEMBER):
        user = get_user_model().objects.create_user(username=email, email=email, password="pw-123456789")
        Membership.objects.create(user=user, organization=self.org, role=role)
        return user


def user_client(user, org=None):
    client = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if org is not None:
        headers["HTTP_X_ORGANIZATION"] = org.slug
    client.credentials(**headers)
    return client


def make_tenant(name="Acme", email="owner@acme.test"):
    owner = get_user_model().objects.create_user(username=email, email=email, password="pw-123456789")
    org = create_organization(name, owner=owner)
    _, raw_key = ApiKey.objects.create_key(org, name="test")
    return Tenant(org=org, owner=owner, api_key=raw_key)


@pytest.fixture(autouse=True)
def clear_cache():
    # Rate-limit counters live in the cache; start every test with none.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def tenant(db):
    return make_tenant()


@pytest.fixture
def other_tenant(db):
    return make_tenant(name="Globex", email="owner@globex.test")


def signed_webhook(client, payload, api_key, secret, timestamp=None):
    body = json.dumps(payload).encode()
    ts = str(int(timestamp if timestamp is not None else time.time()))
    return client.post(
        "/api/webhooks/calls/",
        data=body,
        content_type="application/json",
        HTTP_X_API_KEY=api_key,
        HTTP_X_WEBHOOK_TIMESTAMP=ts,
        HTTP_X_WEBHOOK_SIGNATURE="sha256=" + compute_signature(secret, ts, body),
    )


@pytest.fixture
def post_webhook(api_client, tenant):
    """Send a correctly signed webhook for `tenant`, the way a provider would."""

    def _post(payload, secret=None, timestamp=None, api_key=None):
        return signed_webhook(
            api_client,
            payload,
            api_key=api_key or tenant.api_key,
            secret=secret or tenant.org.webhook_secret,
            timestamp=timestamp,
        )

    return _post


def make_event(event_id, type_, call_id="call_1", timestamp="2026-01-10T10:00:00Z", **data):
    return {"event_id": event_id, "type": type_, "call_id": call_id, "timestamp": timestamp, "data": data}


def full_call(call_id="call_1", duration=125, end_reason="completed", tool_success=True):
    """A realistic sequence of events for one call."""
    return [
        make_event(f"{call_id}_1", "call.started", call_id, "2026-01-10T10:00:00Z",
                   agent_id="clinic-bot", direction="inbound", **{"from": "+919800000001", "to": "+918000000000"}),
        make_event(f"{call_id}_2", "transcript.chunk", call_id, "2026-01-10T10:00:05Z", speaker="agent", text="Hello!"),
        make_event(f"{call_id}_3", "transcript.chunk", call_id, "2026-01-10T10:00:10Z", speaker="caller", text="Hi"),
        make_event(f"{call_id}_4", "tool.called", call_id, "2026-01-10T10:01:00Z",
                   name="book_appointment", success=tool_success),
        make_event(f"{call_id}_5", "call.ended", call_id, "2026-01-10T10:02:05Z",
                   duration_seconds=duration, end_reason=end_reason,
                   usage={"model": "gpt-4o-mini", "prompt_tokens": 2000, "completion_tokens": 500}),
    ]
