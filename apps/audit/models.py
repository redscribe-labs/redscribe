from django.conf import settings
from django.db import models


class AuditLogEntry(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_log_entries",
    )
    actor_username = models.CharField(max_length=150, blank=True, default="")
    actor_role = models.CharField(max_length=32, blank=True, default="")

    action = models.CharField(max_length=150, blank=True, default="")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()

    engagement_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    object_ref = models.CharField(max_length=255, blank=True, default="")

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    query_string = models.CharField(max_length=500, blank=True, default="")
    referer = models.CharField(max_length=500, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    entry_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["engagement_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.actor_username or 'anonymous'} {self.action} [{self.status_code}]"
