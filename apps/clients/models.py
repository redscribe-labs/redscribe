import uuid

from django.conf import settings
from django.db import models


class Client(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="clients_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FindingClientView(models.Model):
    finding = models.ForeignKey("findings.Finding", on_delete=models.CASCADE, related_name="client_views")
    client_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finding_views",
    )
    first_viewed_at = models.DateTimeField(auto_now_add=True)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["finding", "client_user"], name="unique_finding_client_view"),
        ]

    def __str__(self):
        return f"{self.client_user} viewed {self.finding_id}"
