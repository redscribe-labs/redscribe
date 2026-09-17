from django.db import migrations

NEW_PERMISSIONS = [
    (
        "engagements.release_to_client",
        "Approve releasing an engagement's findings to the client portal",
        "Engagements",
    ),
]

# Superadmin always bypasses (is_superadmin=True) regardless of this grant.
# Team Lead reproduces the exact pre-existing hardcoded behavior this
# replaces (apps.engagements.permissions.can_release_engagement_to_client
# used to check is_team_lead_role directly) — nobody else's effective
# access changes.
DEFAULT_GRANTS = {
    "engagements.release_to_client": ["team_lead"],
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
        ("accounts", "0013_granular_admin_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, remove_new_permissions),
    ]
