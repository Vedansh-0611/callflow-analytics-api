"""Outbound webhooks: tell customers when something happens, reliably.

- Each event is stored as a WebhookDelivery per endpoint before anything is
  sent, so a crash never loses it, and the (endpoint, event_id) constraint
  means the same event is never queued twice.
- Requests are signed exactly like the webhooks we accept: HMAC-SHA256 over
  "<timestamp>.<body>" with the endpoint's secret.
- Failures are retried by Celery with exponential backoff (see tasks.py).
"""
import ipaddress
import json
import random
import time
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.renderers import JSONRenderer

from calls.signatures import compute_signature

from .models import WebhookDelivery, WebhookEndpoint

USER_AGENT = "CallFlow-Webhooks/1.0"


def build_payload(org, event_type, event_id, data):
    # Round-trip through DRF's encoder so Decimals and datetimes become plain JSON.
    data = json.loads(JSONRenderer().render(data))
    return {
        "id": event_id,
        "type": event_type,
        "created_at": timezone.now().isoformat(),
        "organization": org.slug,
        "data": data,
    }


def dispatch_event(org, event_type, event_id, data):
    """Queue one event for every active endpoint of `org` that subscribed to it."""
    payload = build_payload(org, event_type, event_id, data)
    queued = []
    for endpoint in WebhookEndpoint.objects.filter(organization=org, is_active=True):
        if event_type not in endpoint.events:
            continue
        delivery, created = WebhookDelivery.objects.get_or_create(
            endpoint=endpoint,
            event_id=event_id,
            defaults={"event_type": event_type, "payload": payload},
        )
        if created:
            queued.append(delivery)
            enqueue(delivery)
    return queued


def enqueue(delivery):
    from .tasks import deliver_webhook

    # After the commit, so the worker can find the row.
    transaction.on_commit(lambda: deliver_webhook.delay(delivery.pk))


def sign_headers(secret, body, event_type, event_id, timestamp=None):
    ts = str(int(timestamp if timestamp is not None else time.time()))
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-CallFlow-Event": event_type,
        "X-CallFlow-Delivery": event_id,
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature": "sha256=" + compute_signature(secret, ts, body),
    }


def attempt_delivery(delivery):
    """POST the event once and record the outcome. Returns True on a 2xx."""
    endpoint = delivery.endpoint
    body = json.dumps(delivery.payload, separators=(",", ":")).encode()
    headers = sign_headers(endpoint.secret, body, delivery.event_type, delivery.event_id)

    status_code, error = None, ""
    try:
        response = requests.post(
            endpoint.url,
            data=body,
            headers=headers,
            timeout=settings.OUTBOUND_WEBHOOK_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        status_code = response.status_code
        if not 200 <= status_code < 300:
            error = f"HTTP {status_code}"
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]

    delivery.attempts += 1
    delivery.last_status_code = status_code
    delivery.last_error = error
    if not error:
        delivery.status = WebhookDelivery.Status.SUCCEEDED
        delivery.delivered_at = timezone.now()
        delivery.next_retry_at = None
    delivery.save()
    return not error


def backoff_seconds(retries, base=None, cap=None, rng=random):
    """30s, 60s, 120s, ... capped, plus up to 10% jitter so a receiver that
    comes back up is not hit by every queued retry in the same second."""
    base = settings.OUTBOUND_WEBHOOK_BACKOFF_BASE if base is None else base
    cap = settings.OUTBOUND_WEBHOOK_BACKOFF_CAP if cap is None else cap
    delay = min(cap, base * 2**retries)
    return delay + rng.uniform(0, delay * 0.1)


def validate_endpoint_url(url):
    """Return an error message, or None if the URL may receive webhooks.

    In production only https is allowed, and obvious internal targets are
    refused so an endpoint cannot be pointed at our own network.
    """
    if settings.ALLOW_INSECURE_WEBHOOK_URLS:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Webhook URLs must use https."
    host = (parsed.hostname or "").lower()
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return "Webhook URLs cannot point at internal hosts."
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return "Webhook URLs cannot point at private IP addresses."
    return None
