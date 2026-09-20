from django.db import migrations

NEW_PERMISSIONS = [
    (
        "catalogue.bulk_manage",
        "Export/import the whole vulnerability catalogue at once",
        "Catalogue",
    ),
    (
        "findings.act_any_assignment",
        "Submit any finding's review/QA decision, regardless of who it's assigned to",
        "Finding Review",
    ),
    (
        "clients.manage",
        "Manage client-portal companies and accounts",
        "Client Portal",
    ),
    (
        "users.manage",
        "⚠ Manage user accounts (create, deactivate, change roles). Someone holding this can also "
        "grant themselves roles.manage and become Superadmin-equivalent — see this category's own warning.",
        "Administration",
    ),
    (
        "roles.manage",
        "⚠ Manage roles and permissions, including this list. Someone holding this can grant themselves "
        "(or anyone) every permission here — effectively Superadmin-equivalent.",
        "Administration",
    ),
    (
        "feature_flags.manage",
        "Manage feature flags",
        "Administration",
    ),
    (
        "licensing.manage",
        "Manage the license key",
        "Administration",
    ),
    (
        "audit_log.manage",
        "View and purge the audit log",
        "Administration",
    ),
    (
        "field_visibility.manage",
        "Manage which finding/catalogue fields are visible",
        "Administration",
    ),
    (
        "branding.manage",
        "Manage firm branding (name, logo) shown on the login page, sidebar, and reports",
        "Administration",
    ),
]

# Superadmin always bypasses (is_superadmin=True) regardless of this grant.
# Every one of these previously stayed hardcoded to is_superadmin_role, so
# nobody but Superadmin gets a default grant here — this migration only
# makes the check delegable via Role Management, it doesn't hand any of
# them out to anyone. clients.manage is the one exception: it reproduces
# apps.clients.permissions.require_client_manager's existing
# Superadmin-or-Team-Lead rule, so Team Lead keeps exactly the access it
# already had.
DEFAULT_GRANTS = {
    "clients.manage": ["team_lead"],
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
        ("accounts", "0012_consultant_loses_engagements_create"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, remove_new_permissions),
    ]
