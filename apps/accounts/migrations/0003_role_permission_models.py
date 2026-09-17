import uuid

import django.db.models.deletion
from django.db import migrations, models


def seed_permissions_and_roles(apps, schema_editor):
    from apps.accounts.permissions_registry import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    permissions_by_codename = {}
    for codename, label, category in PERMISSIONS:
        permission, _created = Permission.objects.get_or_create(
            codename=codename, defaults={"label": label, "category": category}
        )
        permissions_by_codename[codename] = permission

    superadmin, _created = Role.objects.get_or_create(
        slug="superadmin", defaults={"name": "Superadmin", "is_builtin": True, "is_superadmin": True}
    )
    # Given every permission explicitly too, purely so Role Management's
    # UI shows Superadmin as "all checked" without needing special-case
    # rendering — the actual bypass is is_superadmin=True, not this list.
    superadmin.permissions.set(permissions_by_codename.values())

    for slug, codenames in DEFAULT_ROLE_PERMISSIONS.items():
        role, _created = Role.objects.get_or_create(
            slug=slug, defaults={"name": slug.replace("_", " ").title(), "is_builtin": True}
        )
        role.permissions.set(permissions_by_codename[codename] for codename in codenames)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_uuid"),
    ]

    operations = [
        migrations.CreateModel(
            name="Permission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("codename", models.CharField(editable=False, max_length=100, unique=True)),
                ("label", models.CharField(editable=False, max_length=200)),
                ("category", models.CharField(editable=False, max_length=50)),
            ],
            options={
                "ordering": ["category", "label"],
            },
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=50, unique=True)),
                ("slug", models.SlugField(editable=False, max_length=50, unique=True)),
                ("is_builtin", models.BooleanField(default=False, editable=False)),
                ("is_superadmin", models.BooleanField(default=False, editable=False)),
                ("permissions", models.ManyToManyField(blank=True, related_name="roles", to="accounts.permission")),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(seed_permissions_and_roles, migrations.RunPython.noop),
    ]
