from django.db import migrations, models


def populate_value(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    for tag in ClassificationTag.objects.all():
        tag.value = f"{tag.code} – {tag.label}" if tag.label else tag.code
        tag.save(update_fields=["value"])


def revert_value(apps, schema_editor):
    # Best-effort split back into code/label — value entered manually after
    # this migration (not in "code – label" shape) just lands whole in
    # code, label blank. Only matters if this migration is ever reversed.
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    for tag in ClassificationTag.objects.all():
        code, sep, label = tag.value.partition(" – ")
        tag.code = code[:32]
        tag.label = label if sep else ""
        tag.save(update_fields=["code", "label"])


class Migration(migrations.Migration):
    dependencies = [("findings", "0007_vulnerabilitytemplate_status")]

    operations = [
        migrations.RemoveConstraint(
            model_name="classificationtag", name="unique_taxonomy_code",
        ),
        migrations.AddField(
            model_name="classificationtag",
            name="value",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.RunPython(populate_value, revert_value),
        migrations.RemoveField(model_name="classificationtag", name="code"),
        migrations.RemoveField(model_name="classificationtag", name="label"),
        migrations.AlterModelOptions(
            name="classificationtag", options={"ordering": ["taxonomy", "value"]},
        ),
        migrations.AddConstraint(
            model_name="classificationtag",
            constraint=models.UniqueConstraint(fields=["taxonomy", "value"], name="unique_taxonomy_value"),
        ),
    ]
