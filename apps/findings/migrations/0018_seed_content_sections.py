from django.db import migrations

# NOTE: this migration originally seeded 8 default sections here (the old
# fixed RICH_TEXT_FIELD_NAMES tuple's replacement). Per an explicit later
# decision, Finding Structure is no longer pre-seeded at all — a fresh
# install starts with zero ContentSectionDefinition rows, full admin
# customization from scratch. seed_sections() is now a no-op.
#
# This is safe to change here (rather than adding a separate migration
# to undo it) precisely because Django tracks *which migrations have run*,
# not their content — an environment where this migration already applied
# (and already has its seeded rows) is completely unaffected by this edit;
# only a genuinely fresh database, applying this migration for the first
# time, sees the new (empty) behavior. See [[project_no_preseeded_admin_data]].


def seed_sections(apps, schema_editor):
    pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("findings", "0017_remove_finding_business_impact_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_sections, noop_reverse),
    ]
