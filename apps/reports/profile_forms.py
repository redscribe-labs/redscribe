from django import forms

from apps.findings.forms import RichTextField

from .models import ReportProfile, ReportTextBlockDefinition
from .validators import validate_font_name, validate_no_markup_chars, validate_rgba


class ReportProfileCreateForm(forms.ModelForm):
    class Meta:
        model = ReportProfile
        fields = ["name"]


class ReportProfileTemplateForm(forms.Form):
    template = RichTextField(
        required=False,
        help_text="Write the report's document directly. Use heading levels for chapters and subsections, "
        "and type {{ tag_name }} on its own line anywhere a block of content (see the reference list "
        "below) should appear.",
    )

    cover_title = forms.CharField(max_length=255, required=False, label="Cover title")
    classification_label = forms.CharField(
        max_length=64, required=False, label="Classification label",
        help_text="Shown on the cover page and in every page footer.",
    )
    finding_id_prefix = forms.CharField(
        max_length=16, required=False, label="Finding ID prefix",
        help_text='e.g. "V" produces V001, V002, ... — only affects findings assigned an id after a change.',
    )

    body_font = forms.CharField(
        max_length=100, required=False, validators=[validate_font_name], label="Body font",
        help_text="Used for all report text in preview and PDF export. Any Google Font name works "
                   "(e.g. \"Roboto Slab\") — it's fetched once on save and self-hosted from then on, so nothing "
                   "external is contacted again. A non-Google font name (e.g. \"Helvetica\") just uses whatever's "
                   "installed wherever the report is viewed, same as before. Letters, digits, spaces, and "
                   "hyphens only. If this is the instance's default Report Profile, this also becomes the font "
                   "used across the RedScribe web app itself (both the internal app and the client portal), "
                   "not just this report.",
    )
    monospace_font = forms.CharField(
        max_length=100, required=False, validators=[validate_font_name], label="Monospace font",
        help_text="Used for code blocks and inline code. Same Google Fonts support as Body font above — and, "
                   "for the default profile, same effect on the live web app UI.",
    )
    bullet_character = forms.CharField(
        max_length=8, required=False, validators=[validate_no_markup_chars], label="Bullet character",
        help_text="Used for every bulleted list, inline and in tables, across preview/PDF. "
                   "Markdown export always uses \"-\" (part of the Markdown format's own syntax).",
    )
    table_header_color = forms.CharField(
        max_length=64, required=False, validators=[validate_rgba], label="Table header color",
        help_text="Background for every table's header row, across preview/PDF (e.g. \"rgba(30,58,138,1)\"). "
                   "Header text color is picked automatically for contrast, and this same color tints the "
                   "code-block background/border and cover accent too. Markdown tables have no cell styling, "
                   "so this doesn't apply there.",
        widget=forms.TextInput(attrs={"placeholder": "rgba(248,250,252,1)"}),
    )
    empty_cell_background_color = forms.CharField(
        max_length=64, required=False, validators=[validate_rgba], label="Empty cell background color",
        help_text="Background for a severity/status cell (below) whose open/closed color field is left blank, "
                   "across preview/PDF.",
        widget=forms.TextInput(attrs={"placeholder": "rgba(237,238,238,1)"}),
    )
    finding_table_layout = forms.ChoiceField(
        choices=ReportProfile.FindingTableLayout.choices, required=False, label="Finding details layout",
        help_text="How each finding's severity/CVSS/classification/status details are shown: a two-column "
                   "table, or a plain list. Severity/status color highlighting only applies to the table layout.",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.findings.models import Finding

        from .assembly import _DEFAULT_SEVERITY_COLORS

        self.text_blocks = (
            list(ReportTextBlockDefinition.objects.filter(profile=profile, is_active=True))
            if profile is not None else []
        )

        configured_colors = (
            profile.severity_colors if profile is not None and isinstance(profile.severity_colors, dict) else {}
        )
        for severity, severity_label in Finding.Severity.choices:
            defaults = _DEFAULT_SEVERITY_COLORS[severity]
            configured = configured_colors.get(severity) or {}
            for variant in ("open", "closed"):
                # Pre-filling this with the built-in default (rather than
                # leaving it genuinely blank) would mean every profile ends
                # up with an explicit color the moment its edit page is
                # saved, even untouched — silently defeating "empty cell
                # background color" below, since a cell is never actually
                # blank. Show the default as a placeholder hint only.
                self.fields[f"severity_color__{severity}__{variant}"] = forms.CharField(
                    required=False, max_length=64, validators=[validate_rgba],
                    label=f"{severity_label} ({variant})",
                    initial=configured.get(variant, ""),
                    widget=forms.TextInput(attrs={"placeholder": f"Default: {defaults[variant]}"}),
                )

        from .labels import LABEL_DEFAULTS

        configured_labels = profile.labels if profile is not None and isinstance(profile.labels, dict) else {}
        for key, default_text in LABEL_DEFAULTS.items():
            # Same "blank means inherit" pattern as severity colors above —
            # the default only ever shows as a placeholder hint, never a
            # submitted value, so an untouched profile keeps falling back
            # to LABEL_DEFAULTS (see labels.get_label) rather than locking
            # in an explicit copy of the shipped English text.
            self.fields[f"label__{key}"] = forms.CharField(
                required=False, max_length=200,
                initial=configured_labels.get(key, ""),
                widget=forms.TextInput(attrs={"placeholder": f"Default: {default_text}"}),
            )


class ReportTextBlockCreateForm(forms.ModelForm):
    class Meta:
        model = ReportTextBlockDefinition
        fields = ["label", "include_in_remediation_report_only"]
        widgets = {"label": forms.TextInput(attrs={"placeholder": "e.g. Assessment objectives"})}


ReportTextBlockFormSet = forms.modelformset_factory(
    ReportTextBlockDefinition, fields=["label", "is_active", "include_in_remediation_report_only"], extra=0,
)


class ReportSharedTextBlockContentForm(forms.Form):
    content = RichTextField(required=False)


class ReportDocxTemplateUploadForm(forms.Form):
    docx_template = forms.FileField(
        required=True, label="Word (.docx) template",
        help_text="A .docx with {{ tag }} placeholders and a {%p for finding in findings %} loop — "
                   "see the placeholder reference below.",
    )


class ReportDocxStyleMapForm(forms.Form):
    """Fields are built dynamically from STYLE_ROLES x the uploaded template's
    own discovered style catalog — same dynamic-fields-in-__init__ pattern as
    ReportProfileTemplateForm's severity-color/label fields above."""

    def __init__(self, *args, discovered_styles=None, current_map=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .docx_style_roles import STYLE_ROLES

        discovered_styles = discovered_styles or {"paragraph": [], "character": [], "table": []}
        current_map = current_map if isinstance(current_map, dict) else {}
        for role_key, label, bucket in STYLE_ROLES:
            choices = [("", "— not mapped —")] + [(name, name) for name in discovered_styles.get(bucket, [])]
            self.fields[f"role__{role_key}"] = forms.ChoiceField(
                choices=choices, required=False, label=label, initial=current_map.get(role_key, ""),
            )
