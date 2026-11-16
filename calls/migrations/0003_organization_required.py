"""Step 2 of 2: organization is required, ids are unique per organization, and
every index leads with organization because every query filters by it."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0002_add_organization"),
    ]

    operations = [
        migrations.AlterField(
            model_name="call",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="calls", to="accounts.organization"
            ),
        ),
        migrations.AlterField(
            model_name="callevent",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.organization"
            ),
        ),
        migrations.AlterField(model_name="call", name="provider_call_id", field=models.CharField(max_length=64)),
        migrations.AlterField(model_name="callevent", name="event_id", field=models.CharField(max_length=64)),
        migrations.AddConstraint(
            model_name="call",
            constraint=models.UniqueConstraint(fields=("organization", "provider_call_id"), name="unique_call_per_org"),
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.UniqueConstraint(fields=("organization", "event_id"), name="unique_event_per_org"),
        ),
        migrations.RemoveIndex(model_name="call", name="call_started_idx"),
        migrations.RemoveIndex(model_name="call", name="call_status_started_idx"),
        migrations.RemoveIndex(model_name="call", name="call_agent_started_idx"),
        migrations.AddIndex(
            model_name="call",
            index=models.Index(fields=["organization", "started_at"], name="call_org_started_idx"),
        ),
        migrations.AddIndex(
            model_name="call",
            index=models.Index(fields=["organization", "status", "started_at"], name="call_org_status_started_idx"),
        ),
        migrations.AddIndex(
            model_name="call",
            index=models.Index(fields=["organization", "agent_id", "started_at"], name="call_org_agent_started_idx"),
        ),
    ]
