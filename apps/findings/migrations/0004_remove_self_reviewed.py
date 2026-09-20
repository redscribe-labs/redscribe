from django.db import migrations, models


def collapse_self_reviewed_into_qa_approved(apps, schema_editor):
    Finding = apps.get_model("findings", "Finding")
    Finding.objects.filter(workflow_status="SELF_REVIEWED").update(workflow_status="QA_APPROVED")


class Migration(migrations.Migration):

    dependencies = [
        ("findings", "0003_catalogue_uuid_pk"),
    ]

    operations = [
        migrations.RunPython(collapse_self_reviewed_into_qa_approved, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="finding",
            name="workflow_status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("REVIEWED", "Reviewed"),
                    ("REVIEW_CHANGES_REQUESTED", "Changes Requested (Review)"),
                    ("QA_APPROVED", "QA Approved"),
                    ("QA_CHANGES_REQUESTED", "Changes Requested (QA)"),
                ],
                default="DRAFT",
                max_length=32,
            ),
        ),
    ]
