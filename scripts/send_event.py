"""Send signed sample webhooks to a running API, like a telephony provider would.

    export CALLFLOW_API_KEY=cf_...           # printed by `manage.py seed`
    export CALLFLOW_WEBHOOK_SECRET=whsec_...
    python scripts/send_event.py             # full sample call
    python scripts/send_event.py --url http://localhost:8000/api/webhooks/calls/

Uses only the standard library so it works outside the virtualenv too.
"""
import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone


def sign(secret, timestamp, body):
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def send(url, api_key, secret, payload):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Webhook-Timestamp": ts,
            "X-Webhook-Signature": "sha256=" + sign(secret, ts, body),
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def sample_call():
    call_id = "call_" + uuid.uuid4().hex[:12]
    start = datetime.now(timezone.utc) - timedelta(minutes=3)

    def at(seconds):
        return (start + timedelta(seconds=seconds)).isoformat()

    events = [
        ("call.started", at(0), {"agent_id": "clinic-receptionist", "direction": "inbound",
                                 "from": "+919800000001", "to": "+918000000000"}),
        ("transcript.chunk", at(2), {"speaker": "agent", "text": "Hi, how can I help?"}),
        ("transcript.chunk", at(6), {"speaker": "caller", "text": "I'd like to book a checkup."}),
        ("tool.called", at(20), {"name": "book_appointment", "success": True, "latency_ms": 240}),
        ("call.ended", at(95), {"duration_seconds": 95, "end_reason": "completed",
                                "usage": {"model": "gpt-4o-mini", "prompt_tokens": 1800, "completion_tokens": 350}}),
    ]
    return call_id, [
        {"event_id": f"{call_id}_{i}", "type": t, "call_id": call_id, "timestamp": ts, "data": d}
        for i, (t, ts, d) in enumerate(events, start=1)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/api/webhooks/calls/")
    parser.add_argument("--api-key", default=os.environ.get("CALLFLOW_API_KEY", ""))
    parser.add_argument("--secret", default=os.environ.get("CALLFLOW_WEBHOOK_SECRET", ""))
    args = parser.parse_args()
    if not args.api_key or not args.secret:
        parser.error("set CALLFLOW_API_KEY and CALLFLOW_WEBHOOK_SECRET (run `manage.py seed` to get them)")

    call_id, events = sample_call()
    for payload in events:
        status, text = send(args.url, args.api_key, args.secret, payload)
        print(status, payload["type"], text)
    # Resend the last event to show idempotency: expect {"status": "duplicate"}.
    status, text = send(args.url, args.api_key, args.secret, events[-1])
    print(status, "retry of call.ended", text)
    base = args.url.split("/api/")[0]
    print(f'\nView it: curl -H "X-API-Key: $CALLFLOW_API_KEY" {base}/api/calls/{call_id}/')


if __name__ == "__main__":
    main()
