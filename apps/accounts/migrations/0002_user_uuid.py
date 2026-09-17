import uuid

from django.db import migrations, models


def populate_uuids(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        user.uuid = uuid.uuid4()
        user.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        # Step 1: add as nullable, no unique constraint yet — existing rows
        # would otherwise all collide on whatever single value a callable
        # default evaluates to under a plain ALTER TABLE ... DEFAULT.
        migrations.AddField(
            model_name="user",
            name="uuid",
            field=models.UUIDField(null=True, editable=False),
        ),
        # Step 2: give every existing row its own distinct value.
        migrations.RunPython(populate_uuids, migrations.RunPython.noop),
        # Step 3: now safe to enforce NOT NULL + UNIQUE, and set the
        # default so it applies going forward for new rows.
        migrations.AlterField(
            model_name="user",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
