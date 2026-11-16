"""Create a demo workspace and fill it with realistic-looking calls.

    python manage.py seed                 # demo org + user + API key + 200 calls
    python manage.py seed --calls 0       # just the org, user and a fresh API key

The calls are pushed through the real ingestion code, with Celery in eager mode,
so no worker is needed. The last lines are KEY=value pairs that scripts (and CI)
can source to send signed webhooks to the demo org.
"""
import random
import uuid
from datetime import timedelta

from celery import current_app
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import ApiKey, Membership, Organization
from billing.models import UsageCounter
from billing.services import PlanLimitExceeded
from calls.models import Call
from calls.services import ingest_event

DEMO_EMAIL = "demo@callflow.dev"
DEMO_PASSWORD = "callflow-demo"

AGENTS = ["clinic-receptionist", "loan-reminder", "order-support", "lead-qualifier"]
MODELS = ["gpt-4o-mini", "gpt-4o", "claude-haiku"]
END_REASONS = (
    ["completed"] * 12 + ["customer_hangup"] * 4 + ["transferred"] * 2 + ["voicemail"] * 2 + ["error"]
)
TOOLS = ["book_appointment", "lookup_order", "send_sms", "check_balance", "transfer_to_human"]
AGENT_LINES = [
    "Hi, thanks for calling. How can I help you today?",
    "Sure, let me check that for you.",
    "I found two open slots tomorrow, 11 AM or 4 PM.",
    "Done. You will get a confirmation SMS shortly.",
    "Is there anything else I can help with?",
]
CALLER_LINES = [
    "Hi, I wanted to book an appointment.",
    "Can you tell me the status of my order?",
    "Tomorrow works. Let's do 4 PM.",
    "No, that's all. Thank you!",
    "Can I speak to a person please?",
]


class Command(BaseCommand):
    help = "Create a demo organization, user and API key, plus fake calls over the last N days."

    def add_arguments(self, parser):
        parser.add_argument("--calls", type=int, default=200)
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--seed", type=int, default=42, help="random seed for repeatable data")
        parser.add_argument("--flush", action="store_true", help="delete the demo org's calls first")
        parser.add_argument("--org", default="demo", help="slug of the demo organization")

    def handle(self, *args, **options):
        current_app.conf.task_always_eager = True
        rng = random.Random(options["seed"])
        org, user = self.demo_workspace(options["org"])
        raw_key = self.fresh_api_key(org)

        if options["flush"]:
            Call.objects.filter(organization=org).delete()
            UsageCounter.objects.filter(organization=org).delete()

        now = timezone.now()
        created = 0
        try:
            for _ in range(options["calls"]):
                started_at = now - timedelta(
                    days=rng.randint(0, options["days"] - 1),
                    hours=rng.randint(0, 10),
                    minutes=rng.randint(10, 59),
                )
                for payload in self.fake_call_events(rng, started_at):
                    ingest_event(org, payload)
                created += 1
        except PlanLimitExceeded as exc:
            self.stdout.write(self.style.WARNING(f"Stopped early: {exc.detail['detail']} Use --flush to start over."))

        self.stdout.write(self.style.SUCCESS(f"Seeded {created} calls into '{org.slug}'."))
        self.stdout.write(f"Dashboard login: {user.email} / {DEMO_PASSWORD}")
        self.stdout.write(f"CALLFLOW_ORG={org.slug}")
        self.stdout.write(f"CALLFLOW_API_KEY={raw_key}")
        self.stdout.write(f"CALLFLOW_WEBHOOK_SECRET={org.webhook_secret}")

    @transaction.atomic
    def demo_workspace(self, slug):
        org, _ = Organization.objects.get_or_create(slug=slug, defaults={"name": "Acme Health (demo)"})
        user, created = get_user_model().objects.get_or_create(
            username=DEMO_EMAIL, defaults={"email": DEMO_EMAIL, "first_name": "Demo User"}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        Membership.objects.get_or_create(user=user, organization=org, defaults={"role": Membership.Role.OWNER})
        return org, user

    def fresh_api_key(self, org):
        # Keys can only be shown once, so each run revokes the old seed key and
        # prints a new one.
        for old in ApiKey.objects.active().filter(organization=org, name="seed"):
            old.revoke()
        _, raw_key = ApiKey.objects.create_key(org, name="seed")
        return raw_key

    def fake_call_events(self, rng, started_at):
        call_id = f"call_{uuid.UUID(int=rng.getrandbits(128)).hex[:16]}"
        end_reason = rng.choice(END_REASONS)
        short = end_reason in ("voicemail", "error") or rng.random() < 0.1
        duration = rng.randint(4, 14) if short else rng.randint(30, 420)
        clock = started_at
        n = 0

        def event(type_, data, at):
            nonlocal n
            n += 1
            return {
                "event_id": f"{call_id}_evt_{n}",
                "type": type_,
                "call_id": call_id,
                "timestamp": at,
                "data": data,
            }

        events = [
            event(
                "call.started",
                {
                    "agent_id": rng.choice(AGENTS),
                    "direction": rng.choice(["inbound", "inbound", "outbound"]),
                    "from": f"+9198{rng.randint(10000000, 99999999)}",
                    "to": "+918000000000",
                },
                clock,
            )
        ]

        turns = 0 if short else rng.randint(2, 5)
        step = duration / (turns * 2 + 2)
        for i in range(turns):
            clock += timedelta(seconds=step)
            events.append(event("transcript.chunk", {"speaker": "agent", "text": AGENT_LINES[i % 5]}, clock))
            clock += timedelta(seconds=step)
            events.append(event("transcript.chunk", {"speaker": "caller", "text": CALLER_LINES[i % 5]}, clock))
            if i == 1 and rng.random() < 0.6:
                events.append(
                    event(
                        "tool.called",
                        {"name": rng.choice(TOOLS), "success": rng.random() > 0.15, "latency_ms": rng.randint(80, 900)},
                        clock,
                    )
                )

        prompt_tokens = 0 if short else rng.randint(800, 6000)
        events.append(
            event(
                "call.ended",
                {
                    "duration_seconds": duration,
                    "end_reason": end_reason,
                    "usage": {
                        "model": rng.choice(MODELS),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": prompt_tokens // rng.randint(4, 8),
                    },
                },
                started_at + timedelta(seconds=duration),
            )
        )
        return events
