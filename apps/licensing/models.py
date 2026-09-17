from django.conf import settings
from django.db import models


class LicenseKey(models.Model):
    key_text = models.TextField(
        blank=True,
        help_text="The signed license key string provided after purchasing a commercial license. "
        "Leave blank for personal/community use — nothing else changes.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="license_key_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "License key"

    @classmethod
    def get_solo(cls) -> "LicenseKey":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
