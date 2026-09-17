import uuid

from django.conf import settings
from django.db import models

from .validators import validate_font_name, validate_no_markup_chars, validate_rgba

PLACEHOLDER_HELP = [
    ("client_name", "Engagement's client name"),
    ("reference_number", "Engagement's reference/project number"),
    ("scope", "Engagement's recorded scope"),
    ("start_date", "Engagement start date (blank if unset)"),
    ("end_date", "Engagement end date (blank if unset)"),
    ("report_date", "Date the report is generated"),
    ("prepared_by", "Name of the user generating the report"),
]


class ReportSettings(models.Model):
    max_concurrent_report_jobs = models.PositiveIntegerField(default=2)

    firm_name = models.CharField(max_length=255, blank=True, default="")
    firm_logo = models.BinaryField(blank=True, null=True)
    firm_logo_content_type = models.CharField(max_length=64, blank=True, default="")

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="report_settings_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Report settings"

    @classmethod
    def get_solo(cls) -> "ReportSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class ReportConfig(models.Model):
    engagement = models.ForeignKey(
        "engagements.Engagement", null=True, blank=True,
        on_delete=models.CASCADE, related_name="report_configs",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    is_template = models.BooleanField(default=False)

    is_remediation_report = models.BooleanField(default=False)

    profile = models.ForeignKey(
        "ReportProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="report_configs",
    )

    content = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="report_configs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["engagement"], condition=models.Q(is_template=False),
                name="unique_draft_reportconfig_per_engagement",
            ),
        ]

    def __str__(self):
        return self.name or (f"Report config for {self.engagement}" if self.engagement else "Report template")


class ReportTextBlockDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        "reports.ReportProfile",
        on_delete=models.CASCADE, related_name="text_blocks",
    )
    slug = models.SlugField(max_length=64)
    label = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    include_in_remediation_report_only = models.BooleanField(default=False)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="report_text_block_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "slug"], name="unique_profile_text_block_slug"),
        ]

    def __str__(self):
        return self.label


class ReportProfile(models.Model):
    class FindingTableLayout(models.TextChoices):
        TABLE = "table", "Table"
        LIST = "list", "List"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, unique=True)
    template = models.JSONField(default=dict, blank=True)
    block_defaults = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text="The profile a report uses when its ReportConfig has none explicitly chosen.",
    )

    cover_title = models.CharField(max_length=255, blank=True, default="Penetration Test Report")

    classification_label = models.CharField(max_length=64, blank=True, default="Strictly Confidential")

    finding_id_prefix = models.CharField(max_length=16, blank=True, default="F")

    severity_colors = models.JSONField(default=dict, blank=True)

    body_font = models.CharField(max_length=100, blank=True, default="Open Sans", validators=[validate_font_name])
    monospace_font = models.CharField(
        max_length=100, blank=True, default="JetBrains Mono", validators=[validate_font_name],
    )

    bullet_character = models.CharField(
        max_length=8, blank=True, default="•", validators=[validate_no_markup_chars],
    )

    table_header_color = models.CharField(
        max_length=64, blank=True, default="rgba(248,250,252,1)", validators=[validate_rgba],
    )

    empty_cell_background_color = models.CharField(
        max_length=64, blank=True, default="rgba(237,238,238,1)", validators=[validate_rgba],
        help_text="Used for a severity/status table cell whose color field below is left blank.",
    )

    finding_table_layout = models.CharField(
        max_length=16, choices=FindingTableLayout.choices, default=FindingTableLayout.TABLE,
        help_text="How each finding's severity/CVSS/classification/status details are displayed: "
                   "a two-column table, or a plain list.",
    )

    labels = models.JSONField(
        default=dict, blank=True,
        help_text="Overrides for field/column label text baked into the report — see reports.labels.LABEL_DEFAULTS. "
                   "A missing or blank key falls back to the shipped English default.",
    )

    # DOCX export: a superadmin-uploaded .docx with {{ tag }} placeholders
    # and a {%p for finding in findings %} loop, filled in with docxtpl.
    # Stored as a DB blob like every other uploaded binary asset in this
    # app (ReportSettings.firm_logo, CachedGoogleFont.font_data,
    # EncryptedBlob.ciphertext) — apps.reports never uses FileField/MEDIA_ROOT.
    docx_template = models.BinaryField(blank=True, null=True)
    docx_template_filename = models.CharField(max_length=255, blank=True, default="")
    docx_template_content_type = models.CharField(max_length=128, blank=True, default="")
    docx_template_uploaded_at = models.DateTimeField(null=True, blank=True)
    docx_style_map = models.JSONField(
        default=dict, blank=True,
        help_text="Maps each DOCX content role (see reports.docx_style_roles.STYLE_ROLES) to a style name "
                   "from the uploaded template's own style catalog.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="report_profiles_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=models.Q(is_default=True), name="unique_default_report_profile",
            ),
        ]

    def __str__(self):
        return self.name


class ReportJob(models.Model):
    engagement = models.ForeignKey("engagements.Engagement", on_delete=models.CASCADE, related_name="+")
    fmt = models.CharField(max_length=16)
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fmt} export of {self.engagement_id} since {self.started_at}"


class CachedGoogleFont(models.Model):
    family = models.CharField(max_length=100)
    weight = models.CharField(max_length=8, default="400")
    style = models.CharField(max_length=16, default="normal")
    font_format = models.CharField(max_length=16, default="woff2")
    content_type = models.CharField(max_length=64, default="font/woff2")
    font_data = models.BinaryField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["family", "weight", "style"], name="unique_cached_google_font_variant"),
        ]

    def __str__(self):
        return f"{self.family} {self.weight} {self.style}"


class ReportExportLog(models.Model):
    engagement = models.ForeignKey(
        "engagements.Engagement", on_delete=models.CASCADE, related_name="report_export_logs"
    )
    fmt = models.CharField(max_length=16)
    comment = models.TextField(blank=True, default="")
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="report_exports",
    )
    exported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-exported_at"]

    def __str__(self):
        return f"{self.fmt} export of {self.engagement_id} by {self.exported_by} at {self.exported_at}"
