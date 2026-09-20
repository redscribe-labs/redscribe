from django.db import migrations, models


# This seeds exactly one row, deliberately breaking with 0018's "Finding
# Structure is no longer pre-seeded at all" policy. That policy is about
# narrative content sections (Description, Impact, ...) an admin authors and
# fully owns, including whether they exist at all. "Affects" is different: it
# is fixed finding metadata backed by Finding.affects, present on every
# finding regardless of admin configuration — this row is only a
# placement/label handle for it (is_protected=True blocks deletion), not
# admin-authored content, so leaving it out for admins to "add themselves"
# isn't meaningful the way it is for a real content section.
def seed_affects_section(apps, schema_editor):
    ContentSectionDefinition = apps.get_model("findings", "ContentSectionDefinition")
    if ContentSectionDefinition.objects.filter(slug="affects").exists():
        return
    last = ContentSectionDefinition.objects.order_by("-order").first()
    ContentSectionDefinition.objects.create(
        slug="affects", label="Affected Assets", is_protected=True, is_active=True,
        order=(last.order + 10) if last else 10,
    )


def remove_affects_section(apps, schema_editor):
    ContentSectionDefinition = apps.get_model("findings", "ContentSectionDefinition")
    ContentSectionDefinition.objects.filter(slug="affects", is_protected=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("findings", "0020_scanimportrecord"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentsectiondefinition",
            name="is_protected",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(seed_affects_section, remove_affects_section),
    ]
