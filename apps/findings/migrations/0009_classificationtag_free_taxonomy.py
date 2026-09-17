from django.db import migrations, models

# The taxonomy enum this migration is retiring (0002's seed data used these
# codes; 0008 kept them as-is when it introduced `value`). Rewritten here to
# the human-readable form so nothing in the app still displays a raw code
# like "OWASP_TOP10" now that taxonomy is freeform text, not a choice field.
CODE_TO_DISPLAY = {
    "OWASP_TOP10": "OWASP Top 10",
    "MITRE_ATTACK": "MITRE ATT&CK",
    "MITRE_CWE": "MITRE CWE",
}


def rewrite_taxonomy(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    for tag in ClassificationTag.objects.all():
        display = CODE_TO_DISPLAY.get(tag.taxonomy)
        if display and display != tag.taxonomy:
            tag.taxonomy = display
            tag.save(update_fields=["taxonomy"])


def revert_taxonomy(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    reverse_map = {v: k for k, v in CODE_TO_DISPLAY.items()}
    for tag in ClassificationTag.objects.all():
        code = reverse_map.get(tag.taxonomy)
        if code:
            tag.taxonomy = code
            tag.save(update_fields=["taxonomy"])


class Migration(migrations.Migration):
    dependencies = [("findings", "0008_classificationtag_value")]

    operations = [
        migrations.AlterField(
            model_name="classificationtag",
            name="taxonomy",
            field=models.CharField(max_length=64),
        ),
        migrations.RunPython(rewrite_taxonomy, revert_taxonomy),
    ]
