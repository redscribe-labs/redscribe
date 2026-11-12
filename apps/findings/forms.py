from django import forms

from apps.engagements.models import AssetCategory

from .models import ContentSectionDefinition, Finding, TemplateSection, VulnerabilityTemplate
from .validators import (
    sanitize_tiptap_image_srcs,
    sanitize_tiptap_link_hrefs,
    validate_cve_id,
    validate_cvss_consistency,
    validate_cvss_score,
    validate_cvss_vector,
    validate_tiptap_doc_json,
)


class RichTextField(forms.CharField):
    def __init__(self, *, allow_own_blob_images=True, **kwargs):
        kwargs.setdefault("widget", forms.HiddenInput)
        kwargs.setdefault("validators", [validate_tiptap_doc_json])
        self.allow_own_blob_images = allow_own_blob_images
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        value = sanitize_tiptap_image_srcs(value, allow_own_blobs=self.allow_own_blob_images)
        return sanitize_tiptap_link_hrefs(value)


def _section_field_name(slug: str) -> str:
    return f"section__{slug}"


class FindingForm(forms.Form):
    title = forms.CharField(max_length=255)
    # validate_cvss_score / validate_cvss_consistency aren't attached as field
    # validators: they only apply to values the user actually edits (see clean()),
    # so a pre-existing finding with a legacy free-text score stays editable.
    cvss_score = forms.CharField(
        max_length=32, required=False,
        help_text="Number from 0.0 to 10.0, e.g. 8.6 — leave blank if not scored",
    )
    cvss_vector = forms.CharField(
        max_length=255, required=False, validators=[validate_cvss_vector],
        help_text="CVSS:4.0/... (default) or CVSS:3.1/... — leave blank if not scored",
    )
    severity = forms.ChoiceField(
        choices=[("", "— Select severity —"), *Finding.Severity.choices],
        error_messages={"required": "Choose a severity."},
    )
    cve_id = forms.CharField(
        max_length=32, required=False, validators=[validate_cve_id], label="CVE ID",
        widget=forms.TextInput(attrs={
            "pattern": r"CVE-\d{4}-\d{4,}",
            "data-error-pattern": "CVE ID must look like CVE-YYYY-NNNN (year, then 4+ digits).",
        }),
    )
    status = forms.ChoiceField(choices=Finding.Status.choices, initial=Finding.Status.OPEN)
    # The asset class (Internal / External / …) this finding is reported under.
    # Queryset + requiredness are set per-engagement in __init__: required once
    # the engagement has any asset categories, optional otherwise.
    category = forms.ModelChoiceField(
        queryset=AssetCategory.objects.none(), required=False,
        empty_label="— Select group —", label="Asset group",
        help_text="Places this finding in its section of the report (e.g. Internal, External).",
    )
    affects = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False,
        help_text="One affected asset/URL per line",
    )

    def __init__(self, *args, sections=None, engagement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if engagement is not None:
            # The asset-group field only applies when the engagement's report
            # profile is a network-style one that splits findings by group. On a
            # standard profile the field stays hidden (empty queryset) and
            # optional, so those engagements behave exactly as before.
            from apps.reports.assembly import engagement_uses_asset_groups

            if engagement_uses_asset_groups(engagement):
                categories = engagement.asset_categories.all()
                self.fields["category"].queryset = categories
                # Required once there are groups to tag against. If the profile
                # wants groups but none are defined yet, the field stays hidden
                # and the export guard flags any untagged findings instead.
                self.fields["category"].required = categories.exists()
            # The scope-asset values are offered as free-input autocomplete
            # suggestions on the affects textarea (template reads this list).
            self.affects_suggestions = sorted(
                {a.value for a in engagement.scope_assets.all() if a.value}
            )
        else:
            self.affects_suggestions = []
        self.sections = (
            list(sections) if sections is not None
            else list(ContentSectionDefinition.objects.filter(is_active=True))
        )
        for section in self.sections:
            # "affects" is the plain `affects` field above, not a generic
            # rich-text content section — it only appears in self.sections
            # so content_bound_fields() can position it inline at its
            # configured order, alongside the real content sections.
            if section.slug == "affects":
                self.fields["affects"].label = section.label
                continue
            self.fields[_section_field_name(section.slug)] = RichTextField(
                required=False, label=section.label,
            )

    _CVSS_FIELDS = ("cvss_score", "cvss_vector", "severity")

    def clean(self):
        cleaned = super().clean()
        # Only enforce the stricter CVSS rules on values the user actually
        # changed, so editing (and re-saving) a finding created before these
        # rules existed isn't blocked by its legacy score/severity. On create
        # there's no initial, so every entered value counts as changed.
        changed = set(self.changed_data) & set(self._CVSS_FIELDS)
        if not changed:
            return cleaned
        if "cvss_score" in changed and "cvss_score" not in self.errors:
            try:
                validate_cvss_score(cleaned.get("cvss_score"))
            except forms.ValidationError as exc:
                self.add_error("cvss_score", exc)
        if not any(f in self.errors for f in self._CVSS_FIELDS):
            try:
                validate_cvss_consistency(
                    cleaned.get("cvss_score"), cleaned.get("cvss_vector"), cleaned.get("severity"),
                )
            except forms.ValidationError as exc:
                self.add_error("cvss_score", exc)
        return cleaned

    def content_bound_fields(self):
        return [
            (section, self["affects"] if section.slug == "affects" else self[_section_field_name(section.slug)])
            for section in self.sections
        ]

    def section_content(self, slug: str) -> str:
        return self.cleaned_data.get(_section_field_name(slug), "")


class RetestRecordForm(forms.Form):
    status = forms.ChoiceField(
        choices=[c for c in Finding.RetestStatus.choices if c[0] != Finding.RetestStatus.NOT_RETESTED],
        label="Retest result",
    )
    notes = RichTextField(required=False, label="Retest notes / evidence")


MAX_IMPORT_FILE_SIZE = 75 * 1024 * 1024


class ScanImportForm(forms.Form):
    FORMAT_CHOICES = [("NMAP", "Nmap XML"), ("BURP", "Burp Suite XML"), ("NUCLEI", "Nuclei JSON Lines")]

    format = forms.ChoiceField(choices=FORMAT_CHOICES)
    file = forms.FileField(
        help_text="Nmap: output of 'nmap -oX'. Burp: Issues → Report as XML. "
        "Nuclei: output of 'nuclei -jsonl'. Max 75MB.",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_IMPORT_FILE_SIZE:
            raise forms.ValidationError(
                f"File is too large ({uploaded.size // 1024 // 1024}MB) — max {MAX_IMPORT_FILE_SIZE // 1024 // 1024}MB."
            )
        return uploaded


MAX_CATALOGUE_IMPORT_SIZE = 10 * 1024 * 1024


def selected_import_rows(post):
    """Indexes ticked on an import preview, or None when the form was sent
    without a preview (no JS), meaning import everything."""
    if post.get("selection") != "1":
        return None
    return {int(v) for v in post.getlist("include") if v.isdigit()}


class CatalogueImportForm(forms.Form):
    file = forms.FileField(help_text="A .json file exported from this (or another) RedScribe instance's catalogue. Max 10MB.")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_CATALOGUE_IMPORT_SIZE:
            raise forms.ValidationError(
                f"File is too large ({uploaded.size // 1024 // 1024}MB) — max {MAX_CATALOGUE_IMPORT_SIZE // 1024 // 1024}MB."
            )
        return uploaded


class VulnerabilityTemplateForm(forms.Form):
    title = forms.CharField(max_length=255)
    default_cvss_score = forms.CharField(
        max_length=32, required=False, label="Default CVSS score",
        help_text="Number from 0.0 to 10.0, e.g. 8.6 — leave blank if not scored",
    )
    default_cvss_vector = forms.CharField(
        max_length=255, required=False, validators=[validate_cvss_vector], label="Default CVSS vector",
        help_text="CVSS:4.0/... (default) or CVSS:3.1/... — leave blank if not scored",
    )
    default_severity = forms.ChoiceField(choices=Finding.Severity.choices, label="Default severity")

    def __init__(self, *args, sections=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Catalogue templates have no per-engagement asset list — "affects"
        # (protected, backed by Finding.affects) never applies here.
        self.sections = (
            list(sections) if sections is not None
            else list(ContentSectionDefinition.objects.filter(is_active=True).narrative())
        )
        for section in self.sections:
            self.fields[_section_field_name(section.slug)] = RichTextField(
                required=False, allow_own_blob_images=False, label=section.label,
            )

    def clean(self):
        cleaned = super().clean()
        # Validate the default score's format only when it's edited, so a legacy
        # template with a free-text default stays editable (see FindingForm.clean).
        if "default_cvss_score" in self.changed_data and "default_cvss_score" not in self.errors:
            try:
                validate_cvss_score(cleaned.get("default_cvss_score"))
            except forms.ValidationError as exc:
                self.add_error("default_cvss_score", exc)
        return cleaned

    def content_bound_fields(self):
        return [(section, self[_section_field_name(section.slug)]) for section in self.sections]

    def save(self, *, instance=None, created_by=None, classification_tags):
        template = instance or VulnerabilityTemplate(created_by=created_by)
        template.title = self.cleaned_data["title"]
        template.default_cvss_score = self.cleaned_data["default_cvss_score"]
        template.default_cvss_vector = self.cleaned_data["default_cvss_vector"]
        template.default_severity = self.cleaned_data["default_severity"]
        template.save()

        for section in self.sections:
            TemplateSection.objects.update_or_create(
                template=template, definition=section,
                defaults={"content": self.cleaned_data.get(_section_field_name(section.slug), "")},
            )

        template.classifications.set(classification_tags)
        return template
