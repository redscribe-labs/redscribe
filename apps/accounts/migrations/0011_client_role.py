from django.db import migrations


def seed_client_role(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")

    Role.objects.get_or_create(
        slug="client", defaults={"name": "Client", "is_builtin": True, "is_superadmin": False}
    )


def remove_client_role(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(slug="client", is_builtin=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_user_client"),
    ]

    operations = [
        migrations.RunPython(seed_client_role, remove_client_role),
    ]
