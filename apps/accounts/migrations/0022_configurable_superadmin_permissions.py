from django.db import migrations

# These three capabilities were previously gated by a hardcoded is_superadmin_role
# check. This migration makes them delegable via Role Management, following the
# 0013 pattern: Superadmin still bypasses (is_superadmin=True), and nobody else
# gets a default grant — it only makes the checks assignable, it hands nothing out.
NEW_PERMISSIONS = [
    (
        "engagements.access_archived",
        "Access and list archived engagements (otherwise archived engagements are hidden)",
        "Engagements",
    ),
    (
        "engagements.delete_permanent",
        "⚠ Permanently delete an engagement and all of its data (irreversible)",
        "Engagements",
    ),
    (
        "clients.erase_user",
        "⚠ Erase a client user's personal data (irreversible)",
        "Client Portal",
    ),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    created = []
    for codename, label, category in NEW_PERMISSIONS:
        permission, _created = Permission.objects.get_or_create(
            codename=codename, defaults={"label": label, "category": category}
        )
        created.append(permission)

    # Keep Superadmin's explicit permission list complete so Role Management still
    # renders it as "all checked" (the real power is is_superadmin=True, not this list).
    superadmin = Role.objects.filter(is_superadmin=True).first()
    if superadmin is not None:
        superadmin.permissions.add(*created)


def remove_new_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Permission.objects.filter(codename__in=[c for c, _, _ in NEW_PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0021_user_erased_at"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, remove_new_permissions),
    ]
