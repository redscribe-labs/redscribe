from django.db import migrations


def backfill_runs(apps, schema_editor):
    ChecklistItem = apps.get_model("checklist", "ChecklistItem")
    ChecklistRun = apps.get_model("checklist", "ChecklistRun")

    # Pre-existing data has exactly one implicit "run" per engagement (the
    # old one-checklist-per-engagement limit) — give it a generic label
    # since we can't reliably recover which template produced it.
    engagement_ids = ChecklistItem.objects.values_list("engagement_id", flat=True).distinct()
    for engagement_id in engagement_ids:
        run = ChecklistRun.objects.create(engagement_id=engagement_id, label="Checklist")
        ChecklistItem.objects.filter(engagement_id=engagement_id).update(run=run)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("checklist", "0004_checklist_run"),
    ]

    operations = [
        migrations.RunPython(backfill_runs, noop_reverse),
    ]
