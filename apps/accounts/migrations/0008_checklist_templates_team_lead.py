from django.db import migrations

# checklist_templates.manage already exists (seeded in 0003) and was
# superadmin-only by default. Team Lead needs to create/edit checklist
# templates too (see apps.checklist template_views), so grant it here —
# via .add(), never .set(), same reasoning as 0006_reports_trends_permission:
# re-running must never clobber a Superadmin's later Role Management
# customizations.
GRANTS = {
    "checklist_templates.manage": ["team_lead"],
}


def grant_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    for codename, role_slugs in GRANTS.items():
        permission = Permission.objects.filter(codename=codename).first()
        if permission is None:
            continue
        for slug in role_slugs:
            role = Role.objects.filter(slug=slug).first()
            if role is not None:
                role.permissions.add(permission)


def revoke_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    for codename, role_slugs in GRANTS.items():
        permission = Permission.objects.filter(codename=codename).first()
        if permission is None:
            continue
        for slug in role_slugs:
            role = Role.objects.filter(slug=slug).first()
            if role is not None:
                role.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_user_email_notifications_enabled"),
    ]

    operations = [
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
