from django.db import migrations
from django.utils import timezone


def deactivate_users_of_inactive_clients(apps, schema_editor):
    # Deactivating a client now deactivates its portal users too. Clients that were already
    # inactive before that rule existed still have active users, so apply it once here.
    User = apps.get_model("accounts", "User")
    User.objects.filter(role__slug="client", is_active=True, client__is_active=False).update(
        is_active=False, deactivated_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0001_initial"),
        ("accounts", "0021_user_erased_at"),
    ]

    operations = [
        migrations.RunPython(deactivate_users_of_inactive_clients, migrations.RunPython.noop),
    ]
