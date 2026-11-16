"""Step 1 of 2 for multi-tenancy: add a nullable organization and backfill it.

Calls that existed before tenancy are moved into a "Default" organization.
Step 2 (0003) makes the column required and swaps the unique constraints.
"""
import django.db.models.deletion
from django.db import migrations, models


def backfill_organization(apps, schema_editor):
    Call = apps.get_model("calls", "Call")
    CallEvent = apps.get_model("calls", "CallEvent")
    Organization = apps.get_model("accounts", "Organization")

    if not Call.objects.filter(organization__isnull=True).exists():
        return
    org, _ = Organization.objects.get_or_create(slug="default", defaults={"name": "Default"})
    Call.objects.filter(organization__isnull=True).update(organization=org)
    CallEvent.objects.filter(organization__isnull=True).update(organization=org)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("calls", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="call",
            name="organization",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="calls", to="accounts.organization"
            ),
        ),
        migrations.AddField(
            model_name="callevent",
            name="organization",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.organization"
            ),
        ),
        migrations.RunPython(backfill_organization, migrations.RunPython.noop),
    ]
