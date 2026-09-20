import uuid

from django.conf import settings
from django.db import models

from apps.engagements.models import Engagement


class ProjectKey(models.Model):
    engagement = models.OneToOneField(
        Engagement, on_delete=models.CASCADE, related_name="project_key"
    )

    wrapped_key = models.BinaryField()

    key_version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ProjectKey(engagement={self.engagement_id})"


class EncryptedBlob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="blobs")

    content_type = models.CharField(max_length=100)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    ciphertext = models.BinaryField()

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="blobs_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"EncryptedBlob({self.id}, engagement={self.engagement_id})"
