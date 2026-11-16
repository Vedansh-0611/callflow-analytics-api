from django.db import migrations

PLANS = [
    {
        "code": "free",
        "name": "Free",
        "price_cents_per_month": 0,
        "monthly_call_limit": 500,
        "monthly_minute_limit": 1000,
        "api_requests_per_minute": 60,
        "max_api_keys": 2,
        "max_webhook_endpoints": 1,
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_cents_per_month": 4900,
        "monthly_call_limit": 50000,
        "monthly_minute_limit": 100000,
        "api_requests_per_minute": 600,
        "max_api_keys": 20,
        "max_webhook_endpoints": 10,
    },
]


def create_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in PLANS:
        Plan.objects.update_or_create(code=plan["code"], defaults=plan)


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [migrations.RunPython(create_plans, migrations.RunPython.noop)]
