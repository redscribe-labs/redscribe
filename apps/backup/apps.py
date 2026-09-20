from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backup"
    label = "backup"
    verbose_name = "Backup & Restore"
