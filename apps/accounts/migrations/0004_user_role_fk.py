import django.db.models.deletion
from django.db import migrations, models


def populate_role_fk(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Role = apps.get_model("accounts", "Role")

    roles_by_slug = {role.slug: role for role in Role.objects.all()}
    for user in User.objects.all():
        slug = (user.role_old or "consultant").lower()
        user.role = roles_by_slug[slug]
        user.save(update_fields=["role"])


def repopulate_role_old(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        user.role_old = user.role.slug.upper()
        user.save(update_fields=["role_old"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_role_permission_models"),
    ]

    operations = [
        migrations.RenameField(model_name="user", old_name="role", new_name="role_old"),
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="accounts.role",
            ),
        ),
        migrations.RunPython(populate_role_fk, repopulate_role_old),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="accounts.role",
            ),
        ),
        migrations.RemoveField(model_name="user", name="role_old"),
    ]
