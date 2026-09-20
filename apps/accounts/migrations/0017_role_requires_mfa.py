from django.db import migrations, models


def set_superadmin_requires_mfa(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(slug="superadmin").update(requires_mfa=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_mfaattempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="requires_mfa",
            field=models.BooleanField(
                default=False,
                help_text="Local accounts with this role must enroll in TOTP MFA, even if the "
                "instance-wide 'Require MFA' feature flag is off.",
            ),
        ),
        migrations.RunPython(set_superadmin_requires_mfa, migrations.RunPython.noop),
    ]
