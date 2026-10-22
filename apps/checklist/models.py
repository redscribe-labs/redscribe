import uuid

from django.conf import settings
from django.db import models

from apps.engagements.models import Engagement
from apps.findings.models import Finding


class ChecklistTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")

    is_default = models.BooleanField(default=False)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="checklist_templates_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChecklistTemplateItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.CASCADE, related_name="items")

    category = models.CharField(max_length=255)
    code = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=500)
    reference_info = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "category", "code"]

    def __str__(self):
        return f"{self.code} {self.title}".strip()


class ChecklistRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="checklist_runs")
    template = models.ForeignKey(
        ChecklistTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    label = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.label


class ChecklistItem(models.Model):
    class Status(models.TextChoices):
        NOT_TESTED = "NOT_TESTED", "Not Tested"
        TESTED_NO_FINDING = "TESTED_NO_FINDING", "Tested — No Finding"
        TESTED_FINDING_RAISED = "TESTED_FINDING_RAISED", "Tested — Finding Raised"
        NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"
        BLOCKED = "BLOCKED", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ChecklistRun, on_delete=models.CASCADE, related_name="items")

    category = models.CharField(max_length=255)
    code = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=500)
    reference_info = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NOT_TESTED)
    findings = models.ManyToManyField(Finding, blank=True, related_name="checklist_items")

    test_results_ciphertext = models.BinaryField(null=True, blank=True)
    # Why a Blocked check couldn't be tested; encrypted like test results.
    blocked_reason_ciphertext = models.BinaryField(null=True, blank=True)

    # What was actually covered (endpoints, parameters), one per line; encrypted.
    scope_tested_ciphertext = models.BinaryField(null=True, blank=True)

    # Who last set the outcome, and when. Cleared if it goes back to Not Tested.
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    tested_at = models.DateTimeField(null=True, blank=True)

    # Who on the team owns this check. Optional.
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_checklist_items",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "category", "code"]

    def __str__(self):
        return f"{self.code} {self.title}".strip()


class ChecklistItemComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checklist_item = models.ForeignKey(ChecklistItem, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="checklist_comments",
    )
    body_ciphertext = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.checklist_item_id}"


class ChecklistItemEvent(models.Model):
    """What happened to a check, for its Activity list. Only labels and names
    are stored here, never the encrypted text itself."""

    class Kind(models.TextChoices):
        STATUS = "STATUS", "Outcome changed"
        ASSIGNEE = "ASSIGNEE", "Assignee changed"
        EVIDENCE = "EVIDENCE", "Test results edited"
        SCOPE = "SCOPE", "What was tested edited"
        FINDINGS = "FINDINGS", "Linked findings changed"
        COMMENT = "COMMENT", "Comment added"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(ChecklistItem, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    from_value = models.CharField(max_length=255, blank=True, default="")
    to_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.item_id}"
