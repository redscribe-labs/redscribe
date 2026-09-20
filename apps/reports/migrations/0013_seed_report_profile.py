from django.db import migrations


def seed(apps, schema_editor):
    # NOTE: this used to seed 13 ReportTextBlockDefinition rows and one
    # "Default" ReportProfile (a node-tree `structure`, later replaced).
    # Per an explicit later decision, Report Profiles are no longer
    # pre-seeded at all — a fresh install starts with zero profiles and
    # zero text blocks, full admin customization from scratch. This is
    # safe to edit here rather than adding a migration to undo it: Django
    # tracks which migrations have *run*, not their content, so an
    # environment where this migration already applied (and already has
    # its seeded rows) is entirely unaffected by this edit — only a
    # genuinely fresh database, applying this migration for the first
    # time, sees the new (empty) behavior. See
    # [[project_no_preseeded_admin_data]]. Later migrations in this app
    # (0014, 0015) that rebuild/rename "the Default profile" all do so via
    # filter().update()/update_or_create() guarded to be no-ops when it
    # doesn't exist — see their own comments.
    pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0012_reportprofile_reportconfig_profile_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, noop_reverse),
    ]
