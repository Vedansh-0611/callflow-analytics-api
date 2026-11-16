import json

import pytest
import requests
from celery.exceptions import Retry

from calls.signatures import verify_signature
from outbound import services
from outbound.models import WebhookDelivery, WebhookEndpoint
from outbound.tasks import deliver_webhook
from tests.conftest import full_call

pytestmark = pytest.mark.django_db


class FakeReceiver:
    """Stands in for requests.post. Answers with the given status codes in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, data, headers, timeout, allow_redirects):
        self.requests.append({"url": url, "body": data, "headers": headers})
        outcome = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(outcome, Exception):
            raise outcome
        return type("Response", (), {"status_code": outcome})()


@pytest.fixture
def receiver(monkeypatch):
    def install(*responses):
        fake = FakeReceiver(*responses)
        monkeypatch.setattr(services.requests, "post", fake)
        return fake

    return install


@pytest.fixture
def endpoint(tenant):
    return WebhookEndpoint.objects.create(
        organization=tenant.org, url="https://hooks.example.com/callflow", events=["call.summarized"]
    )


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    # Eager Celery runs retries inline; record the delays instead of waiting.
    delays = []
    monkeypatch.setattr("outbound.tasks.backoff_seconds", lambda retries: delays.append(retries) or 0)
    return delays


def finish_call(post_webhook, django_capture_on_commit_callbacks, call_id="call_1"):
    with django_capture_on_commit_callbacks(execute=True):
        for payload in full_call(call_id):
            post_webhook(payload)


def test_summarized_call_is_delivered_signed(endpoint, receiver, post_webhook, django_capture_on_commit_callbacks):
    fake = receiver(200)
    finish_call(post_webhook, django_capture_on_commit_callbacks)

    assert len(fake.requests) == 1
    sent = fake.requests[0]
    body = json.loads(sent["body"])
    assert sent["url"] == endpoint.url
    assert body["type"] == "call.summarized"
    assert body["id"] == "call.summarized.call_1"
    assert body["data"]["id"] == "call_1"
    assert "booking_made" in body["data"]["outcome_tags"]
    assert sent["headers"]["X-CallFlow-Delivery"] == body["id"]
    # The receiver can verify it with the same code we use for inbound webhooks.
    verify_signature(endpoint.secret, sent["headers"]["X-Webhook-Timestamp"],
                     sent["headers"]["X-Webhook-Signature"], sent["body"])

    delivery = WebhookDelivery.objects.get()
    assert (delivery.status, delivery.attempts, delivery.last_status_code) == ("succeeded", 1, 200)


@pytest.fixture
def run_like_a_worker():
    """In eager mode Celery runs each retry inline, right away. Turning off
    exception propagation lets the retry chain play out the way a worker
    would, minus the waiting."""
    conf = deliver_webhook.app.conf
    conf.update(task_eager_propagates=False)

    def run(delivery):
        deliver_webhook.apply(args=[delivery.pk])
        delivery.refresh_from_db()
        return delivery

    yield run
    conf.update(task_eager_propagates=True)


def test_failures_are_retried_with_backoff_until_success(endpoint, receiver, no_backoff_wait, run_like_a_worker):
    fake = receiver(500, requests.ConnectionError("refused"), 200)
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event_id="e1", event_type="ping", payload={})

    delivery = run_like_a_worker(delivery)

    assert len(fake.requests) == 3
    assert delivery.status == "succeeded"
    assert delivery.attempts == 3
    assert no_backoff_wait == [0, 1]  # backoff asked for retry 0, then retry 1


def test_failed_attempt_schedules_the_next_retry(endpoint, receiver, monkeypatch):
    receiver(requests.ConnectionError("refused"))
    monkeypatch.setattr("outbound.tasks.backoff_seconds", lambda retries: 30)
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event_id="e1", event_type="ping", payload={})

    with pytest.raises(Retry):
        deliver_webhook(delivery.pk)  # called directly: just one attempt

    delivery.refresh_from_db()
    assert delivery.status == "pending"
    assert delivery.attempts == 1
    assert delivery.last_error.startswith("ConnectionError")
    assert delivery.next_retry_at is not None


def test_gives_up_after_max_retries(endpoint, receiver, run_like_a_worker):
    fake = receiver(503)
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event_id="e1", event_type="ping", payload={})

    delivery = run_like_a_worker(delivery)

    assert delivery.status == "failed"
    assert delivery.attempts == deliver_webhook.max_retries + 1
    assert len(fake.requests) == deliver_webhook.max_retries + 1
    assert delivery.last_error == "HTTP 503"
    assert delivery.next_retry_at is None


def test_resummarizing_does_not_send_again(endpoint, receiver, post_webhook, django_capture_on_commit_callbacks):
    from calls.models import Call
    from calls.tasks import summarize_call

    fake = receiver(200)
    finish_call(post_webhook, django_capture_on_commit_callbacks)
    summarize_call(Call.objects.get().pk)

    assert len(fake.requests) == 1
    assert WebhookDelivery.objects.count() == 1


def test_dispatch_is_idempotent_per_event_id(tenant, endpoint, receiver, django_capture_on_commit_callbacks):
    receiver(200)
    with django_capture_on_commit_callbacks(execute=True):
        services.dispatch_event(tenant.org, "call.summarized", "evt_1", {})
        services.dispatch_event(tenant.org, "call.summarized", "evt_1", {})
    assert WebhookDelivery.objects.count() == 1


def test_delivered_task_is_not_resent(endpoint, receiver, tenant):
    fake = receiver(200)
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event_id="e", event_type="ping", payload={})
    deliver_webhook(delivery.pk)
    deliver_webhook(delivery.pk)
    assert len(fake.requests) == 1


def test_inactive_and_unsubscribed_endpoints_get_nothing(tenant, receiver, django_capture_on_commit_callbacks):
    fake = receiver(200)
    WebhookEndpoint.objects.create(organization=tenant.org, url="https://a.example.com", events=["call.summarized"],
                                   is_active=False)
    with django_capture_on_commit_callbacks(execute=True):
        services.dispatch_event(tenant.org, "something.else", "evt_1", {})
    assert fake.requests == []


def test_other_orgs_endpoints_get_nothing(endpoint, other_tenant, receiver, django_capture_on_commit_callbacks):
    fake = receiver(200)
    with django_capture_on_commit_callbacks(execute=True):
        services.dispatch_event(other_tenant.org, "call.summarized", "evt_1", {})
    assert fake.requests == []


def test_backoff_grows_exponentially_and_is_capped(settings):
    class NoJitter:
        @staticmethod
        def uniform(a, b):
            return 0

    delays = [services.backoff_seconds(n, base=30, cap=600, rng=NoJitter) for n in range(7)]
    assert delays == [30, 60, 120, 240, 480, 600, 600]
    assert 30 <= services.backoff_seconds(0, base=30, cap=600) <= 33


# --- API ---------------------------------------------------------------------


def test_create_endpoint_shows_secret_once(tenant):
    client = tenant.client()
    response = client.post("/api/webhook-endpoints/", {"url": "https://hooks.example.com/x"}, format="json")

    assert response.status_code == 201
    assert response.json()["secret"].startswith("whsec_")
    assert response.json()["events"] == ["call.summarized"]
    assert "secret" not in client.get("/api/webhook-endpoints/").json()[0]


def test_rotate_secret(tenant, endpoint):
    old = endpoint.secret
    response = tenant.client().post(f"/api/webhook-endpoints/{endpoint.pk}/rotate-secret/")
    assert response.status_code == 200
    assert response.json()["secret"] != old


@pytest.mark.parametrize(
    "url,message",
    [
        ("http://hooks.example.com/x", "https"),
        ("https://localhost/x", "internal"),
        ("https://10.0.0.5/x", "private"),
        ("https://169.254.169.254/latest", "private"),
    ],
)
def test_unsafe_urls_are_rejected_in_production(tenant, settings, url, message):
    settings.ALLOW_INSECURE_WEBHOOK_URLS = False
    response = tenant.client().post("/api/webhook-endpoints/", {"url": url}, format="json")
    assert response.status_code == 400
    assert message in response.json()["url"][0]


def test_unknown_event_type_is_rejected(tenant):
    response = tenant.client().post(
        "/api/webhook-endpoints/", {"url": "https://a.example.com", "events": ["call.exploded"]}, format="json"
    )
    assert response.status_code == 400


def test_endpoint_count_is_limited_by_plan(tenant, endpoint):
    # Free allows one endpoint.
    response = tenant.client().post("/api/webhook-endpoints/", {"url": "https://b.example.com"}, format="json")
    assert response.status_code == 402
    assert response.json()["limit"] == "webhook_endpoints"


def test_test_ping_and_delivery_log(tenant, endpoint, receiver, django_capture_on_commit_callbacks):
    fake = receiver(204)
    client = tenant.client()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/api/webhook-endpoints/{endpoint.pk}/test/")
    assert response.status_code == 202
    assert json.loads(fake.requests[0]["body"])["type"] == "ping"

    log = client.get(f"/api/webhook-endpoints/{endpoint.pk}/deliveries/").json()
    assert [(d["event_type"], d["status"], d["last_status_code"]) for d in log] == [("ping", "succeeded", 204)]


def test_endpoints_are_tenant_scoped_and_admin_only(tenant, other_tenant, endpoint):
    assert other_tenant.client().get(f"/api/webhook-endpoints/{endpoint.pk}/").status_code == 404
    assert other_tenant.client().delete(f"/api/webhook-endpoints/{endpoint.pk}/").status_code == 404
    assert other_tenant.client().get("/api/webhook-endpoints/").json() == []
    member = tenant.add_user("m@acme.test")
    assert tenant.client(member).get("/api/webhook-endpoints/").status_code == 403
    assert tenant.key_client().get("/api/webhook-endpoints/").status_code == 403
