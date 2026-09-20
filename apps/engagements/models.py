import uuid

from django.conf import settings
from django.db import models


class Engagement(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        IN_REVIEW = "IN_REVIEW", "In Review"
        QA = "QA", "QA"
        APPROVED = "APPROVED", "Approved"
        DELIVERED = "DELIVERED", "Delivered"
        AWAITING_REMEDIATION_TEST = "AWAITING_REMEDIATION_TEST", "Awaiting Remediation Test"
        REMEDIATION_TEST = "REMEDIATION_TEST", "Remediation Test"
        CLOSED = "CLOSED", "Closed"

    class TestType(models.TextChoices):
        WEB_APPLICATION = "WEB_APPLICATION", "Web Application Penetration Test"
        NETWORK = "NETWORK", "Network Penetration Test"
        VULNERABILITY_SCAN = "VULNERABILITY_SCAN", "Vulnerability Scan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    client_name = models.CharField(max_length=255)
    client = models.ForeignKey(
        "clients.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="engagements",
    )
    reference_number = models.CharField(max_length=64, blank=True, default="")
    scope = models.TextField(blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.IN_PROGRESS)
    test_type = models.CharField(max_length=32, choices=TestType.choices, blank=True, default="")

    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    client_release_approved = models.BooleanField(default=False)
    client_release_approved_at = models.DateTimeField(null=True, blank=True)
    client_release_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements_released",
    )

    default_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements_as_default_reviewer",
    )
    default_qa = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements_as_default_qa",
    )
    default_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements_as_default_approver",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.client_name


class EngagementMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="engagement_memberships"
    )
    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, related_name="memberships"
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="memberships_granted",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "engagement"], name="unique_engagement_membership"),
        ]

    def __str__(self):
        return f"{self.user} on {self.engagement}"


class ScopeChangeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, related_name="scope_change_requests"
    )
    proposed_scope = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="scope_change_requests_made",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="scope_change_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Scope change for {self.engagement} ({self.status})"


class EngagementStatusHistory(models.Model):
    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, related_name="status_history"
    )
    status = models.CharField(max_length=32, choices=Engagement.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagement_status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["changed_at"]

    def __str__(self):
        return f"{self.engagement} -> {self.status} at {self.changed_at}"
