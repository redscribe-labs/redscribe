from django.db import migrations

NEW_PERMISSIONS = [
    ("catalogue.approve", "Approve draft vulnerability catalogue entries", "Catalogue"),
    ("catalogue.delete_any", "Delete any catalogue entry, including ones created by someone else", "Catalogue"),
]

# Which built-in roles get each new permission by default. Uses .add(),
# never .set() — a Superadmin may have already customized these roles'
# permissions via Role Management, and this must layer a new grant on top
# without touching anything else they've configured.
DEFAULT_GRANTS = {
    "catalogue.approve": ["team_lead", "senior"],
    "catalogue.delete_any": ["team_lead"],
}


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    permissions_by_codename = {}
    for codename, label, category in NEW_PERMISSIONS:
        permission, _created = Permission.objects.get_or_create(
            codename=codename, defaults={"label": label, "category": category}
        )
        permissions_by_codename[codename] = permission

    # Superadmin's permission list is informational only (is_superadmin=True
    # is the actual bypass) but kept in sync so Role Management shows it as
    # "all checked" — see 0003_role_permission_models's seed function.
    superadmin = Role.objects.filter(is_superadmin=True).first()
    if superadmin is not None:
        superadmin.permissions.add(*permissions_by_codename.values())

    for codename, role_slugs in DEFAULT_GRANTS.items():
        permission = permissions_by_codename[codename]
        for slug in role_slugs:
            role = Role.objects.filter(slug=slug).first()
            if role is not None:
                role.permissions.add(permission)


def remove_new_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Permission.objects.filter(codename__in=[codename for codename, _, _ in NEW_PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_role_fk"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, remove_new_permissions),
    ]
