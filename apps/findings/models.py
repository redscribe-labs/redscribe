import uuid

from django.conf import settings
from django.db import models

from apps.engagements.models import Engagement

from .validators import validate_cve_id, validate_cvss_vector


class ClassificationTag(models.Model):
    taxonomy = models.CharField(max_length=64)
    value = models.CharField(max_length=255)

    class Meta:
        ordering = ["taxonomy", "value"]
        constraints = [
            models.UniqueConstraint(fields=["taxonomy", "value"], name="unique_taxonomy_value"),
        ]

    def __str__(self):
        return f"[{self.taxonomy}] {self.value}"


def document_sections(definitions, values, *, encrypted=False, label_overrides=None):
    labels = label_overrides or {}
    sections = []
    for definition in definitions:
        content = values.get(definition.slug)
        if not content:
            continue
        sections.append({
            "field_name": definition.slug,
            "label": labels.get(definition.slug, definition.label),
            "content_json": content,
            "encrypted": encrypted,
        })
    return sections


class ContentSectionDefinitionQuerySet(models.QuerySet):
    def narrative(self):
        """Excludes protected metadata slots (currently just "affects") from
        the generic FindingSection/TemplateSection content pipeline — those
        are backed by a dedicated Finding field instead, and have no content
        of the kind this queryset's callers read/write."""
        return self.exclude(is_protected=True)


class ContentSectionDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    supports_image_upload = models.BooleanField(default=False)

    portal_visible = models.BooleanField(default=False)

    include_in_remediation_report_only = models.BooleanField(default=False)

    is_import_target = models.BooleanField(default=False)

    # A permanent, non-deletable slot (currently only "affects") — admins can
    # still reposition and rename it like any other section, but its content
    # comes from a dedicated Finding field rather than generic
    # FindingSection/TemplateSection storage, and it can never be deleted.
    is_protected = models.BooleanField(default=False)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="content_section_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ContentSectionDefinitionQuerySet.as_manager()

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.label


class FindingSection(models.Model):
    finding = models.ForeignKey("Finding", on_delete=models.CASCADE, related_name="sections")
    definition = models.ForeignKey(
        ContentSectionDefinition, on_delete=models.CASCADE, related_name="finding_sections"
    )
    content_ciphertext = models.BinaryField()

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["definition__order"]
        constraints = [
            models.UniqueConstraint(fields=["finding", "definition"], name="unique_finding_section"),
        ]

    def __str__(self):
        return f"{self.finding_id}: {self.definition.slug}"


class TemplateSection(models.Model):
    template = models.ForeignKey("VulnerabilityTemplate", on_delete=models.CASCADE, related_name="sections")
    definition = models.ForeignKey(
        ContentSectionDefinition, on_delete=models.CASCADE, related_name="template_sections"
    )
    content = models.TextField(blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["definition__order"]
        constraints = [
            models.UniqueConstraint(fields=["template", "definition"], name="unique_template_section"),
        ]

    def __str__(self):
        return f"{self.template_id}: {self.definition.slug}"


class Finding(models.Model):
    class Severity(models.TextChoices):
        CRITICAL = "CRITICAL", "Critical"
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"
        INFORMATIONAL = "INFORMATIONAL", "Informational"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    class WorkflowStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        REVIEWED = "REVIEWED", "Reviewed"
        REVIEW_CHANGES_REQUESTED = "REVIEW_CHANGES_REQUESTED", "Changes Requested (Review)"
        QA_APPROVED = "QA_APPROVED", "QA Approved"
        QA_CHANGES_REQUESTED = "QA_CHANGES_REQUESTED", "Changes Requested (QA)"

    class RetestStatus(models.TextChoices):
        NOT_RETESTED = "NOT_RETESTED", "Not Retested"
        FIXED = "FIXED", "Fixed"
        NOT_FIXED = "NOT_FIXED", "Not Fixed"
        PARTIALLY_FIXED = "PARTIALLY_FIXED", "Partially Fixed"
        RISK_ACCEPTED = "RISK_ACCEPTED", "Risk Accepted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="findings")

    title = models.CharField(max_length=255)

    cvss_score = models.CharField(max_length=32, blank=True, default="")
    cvss_vector = models.CharField(max_length=255, blank=True, default="", validators=[validate_cvss_vector])
    severity = models.CharField(max_length=16, choices=Severity.choices)

    classifications = models.ManyToManyField(ClassificationTag, related_name="findings")

    cve_id = models.CharField(max_length=32, blank=True, default="", validators=[validate_cve_id])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    display_id = models.CharField(max_length=32, blank=True, default="")

    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    affects = models.TextField(blank=True, default="")

    workflow_status = models.CharField(
        max_length=32, choices=WorkflowStatus.choices, default=WorkflowStatus.DRAFT
    )

    retest_status = models.CharField(
        max_length=32, choices=RetestStatus.choices, default=RetestStatus.NOT_RETESTED
    )

    assigned_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="findings_to_review",
    )
    assigned_qa = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="findings_to_qa",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="findings_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        return [line.strip() for line in (text or "").splitlines() if line.strip()]

    @property
    def affects_list(self) -> list[str]:
        return self._split_lines(self.affects)


class RetestRecord(models.Model):
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="retest_records")
    status = models.CharField(max_length=32, choices=Finding.RetestStatus.choices)

    notes_ciphertext = models.BinaryField(null=True, blank=True)

    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="retest_records_logged",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_status_display()} retest of {self.finding_id} by {self.tested_by}"


class VulnerabilityTemplate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_QA = "PENDING_QA", "Pending QA"
        APPROVED = "APPROVED", "Approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    default_severity = models.CharField(max_length=16, choices=Finding.Severity.choices)
    default_cvss_score = models.CharField(max_length=32, blank=True, default="")
    default_cvss_vector = models.CharField(
        max_length=255, blank=True, default="", validators=[validate_cvss_vector]
    )

    classifications = models.ManyToManyField(ClassificationTag, related_name="vulnerability_templates")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="vulnerability_templates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class VulnerabilityTemplateApprovedVersion(models.Model):
    """Frozen copy of a VulnerabilityTemplate's content as of its most recent approval.

    Editing an approved template drops its live status back to Draft/Pending QA immediately
    (see catalogue_views.template_edit), so the live row can't be trusted as "vetted" content
    the moment someone starts revising it. This snapshot is what importing into an engagement
    falls back to while the live row is unapproved but a previously-approved version exists —
    replaced wholesale on each (re-)approval, cleared if an approver explicitly reverts approval.
    """
    template = models.OneToOneField(
        VulnerabilityTemplate, on_delete=models.CASCADE, related_name="approved_version",
    )

    title = models.CharField(max_length=255)
    default_severity = models.CharField(max_length=16, choices=Finding.Severity.choices)
    default_cvss_score = models.CharField(max_length=32, blank=True, default="")
    default_cvss_vector = models.CharField(max_length=255, blank=True, default="")
    classifications = models.ManyToManyField(ClassificationTag, related_name="+")
    sections = models.JSONField(default=dict)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    approved_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Approved version of {self.template_id} @ {self.approved_at}"

    @classmethod
    def snapshot(cls, template, *, approved_by):
        sections = {
            ts.definition.slug: ts.content for ts in template.sections.select_related("definition")
        }
        version, _ = cls.objects.update_or_create(
            template=template,
            defaults={
                "title": template.title,
                "default_severity": template.default_severity,
                "default_cvss_score": template.default_cvss_score,
                "default_cvss_vector": template.default_cvss_vector,
                "sections": sections,
                "approved_by": approved_by,
            },
        )
        version.classifications.set(template.classifications.all())
        return version


class CommentThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="comment_threads")
    field_name = models.CharField(max_length=64)

    start_pos = models.PositiveIntegerField()
    end_pos = models.PositiveIntegerField()

    anchored_text_ciphertext = models.BinaryField()

    resolved = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="comment_threads_started",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["field_name", "start_pos"]

    def __str__(self):
        return f"Thread on {self.finding_id}.{self.field_name} [{self.start_pos}:{self.end_pos}]"


class CommentEntry(models.Model):
    thread = models.ForeignKey(CommentThread, on_delete=models.CASCADE, related_name="entries")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="comment_entries",
    )
    body_ciphertext = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on thread {self.thread_id}"


class ScanImportRecord(models.Model):
    """Audit/appendix record of a scanner import — metadata only (tool,
    filename, when, by whom, how many findings it produced). The raw
    uploaded file itself is never persisted: it's parsed into Finding rows
    by apps.findings.scan_import.import_scan() and discarded, same as
    before this model existed. This exists so a report can document what
    scanning was actually done on an engagement without dumping potentially
    huge raw tool output into the deliverable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="scan_imports")
    source_format = models.CharField(max_length=16)  # matches apps.findings.scan_import.PARSERS keys
    filename = models.CharField(max_length=255, blank=True, default="")
    findings_created = models.PositiveIntegerField(default=0)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="scan_imports",
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["imported_at"]

    def __str__(self):
        return f"{self.source_format} import on {self.engagement_id} ({self.imported_at:%Y-%m-%d})"
