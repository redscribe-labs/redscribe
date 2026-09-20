import uuid

from django.conf import settings
from django.db import models

from apps.engagements.models import Engagement
from apps.findings.models import Finding


class Notification(models.Model):
    class Verb(models.TextChoices):
        REVIEWER_ASSIGNED = "REVIEWER_ASSIGNED", "Assigned as reviewer"
        QA_ASSIGNED = "QA_ASSIGNED", "Assigned as QA approver"
        SCOPE_CHANGE_APPROVED = "SCOPE_CHANGE_APPROVED", "Scope change approved"
        SCOPE_CHANGE_REJECTED = "SCOPE_CHANGE_REJECTED", "Scope change rejected"
        APPROVAL_READY = "APPROVAL_READY", "Engagement ready for approval"
        REVIEWED = "REVIEWED", "Finding reviewed"
        REVIEW_CHANGES_REQUESTED = "REVIEW_CHANGES_REQUESTED", "Review changes requested"
        QA_APPROVED = "QA_APPROVED", "Finding QA approved"
        QA_CHANGES_REQUESTED = "QA_CHANGES_REQUESTED", "QA changes requested"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="notifications_sent",
    )
    verb = models.CharField(max_length=32, choices=Verb.choices)
    message = models.CharField(max_length=500)

    finding = models.ForeignKey(
        Finding, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )
    engagement = models.ForeignKey(
        Engagement, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )

    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_verb_display()} -> {self.recipient} [{'read' if self.read else 'unread'}]"
