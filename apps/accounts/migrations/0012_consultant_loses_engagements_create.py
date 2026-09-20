from django.db import migrations


def remove_engagements_create_from_consultant(apps, schema_editor):
    """
    Consultant used to carry engagements.create by default (see
    apps.accounts.permissions_registry's DEFAULT_ROLE_PERMISSIONS), but the
    engagement-create form now requires linking a client-portal company,
    and that picker lists every active client firm-wide — too broad for a
    role that should only see engagements it's explicitly a member of.
    Revoke it from whatever Consultant role already exists in the DB.
    m2m .remove() is idempotent, so this is safe to run even if a
    Superadmin already customized Consultant's permissions via Role
    Management and removed it themselves.
    """
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")

    consultant = Role.objects.filter(slug="consultant").first()
    permission = Permission.objects.filter(codename="engagements.create").first()
    if consultant is not None and permission is not None:
        consultant.permissions.remove(permission)


def restore_engagements_create_to_consultant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")

    consultant = Role.objects.filter(slug="consultant").first()
    permission = Permission.objects.filter(codename="engagements.create").first()
    if consultant is not None and permission is not None:
        consultant.permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_client_role"),
    ]

    operations = [
        migrations.RunPython(
            remove_engagements_create_from_consultant, restore_engagements_create_to_consultant
        ),
    ]
