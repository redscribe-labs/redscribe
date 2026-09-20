from django.apps import AppConfig


class ChecklistConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.checklist"
    label = "checklist"
    verbose_name = "Checklist"
