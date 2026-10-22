from django import forms

from apps.engagements.access import users_with_access
from apps.findings.forms import MAX_IMPORT_FILE_SIZE, RichTextField

from .models import ChecklistItem


class ChecklistTemplateForm(forms.Form):
    name = forms.CharField(max_length=255, help_text="Must be unique across templates")
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    set_default = forms.BooleanField(
        required=False, label="Use as the default template for new engagement checklists",
    )


class ChecklistTemplateItemForm(forms.Form):
    category = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"list": "template-item-categories"}))
    code = forms.CharField(max_length=32, required=False)
    title = forms.CharField(max_length=500)
    reference_info = RichTextField(required=False, allow_own_blob_images=False)


class ChecklistImportForm(forms.Form):
    FORMAT_CHOICES = [("json", "JSON"), ("csv", "CSV")]

    name = forms.CharField(max_length=255, help_text="e.g. 'OWASP WSTG' — re-uploading the same name replaces its items")
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    format = forms.ChoiceField(choices=FORMAT_CHOICES)
    file = forms.FileField(
        help_text="JSON: a list of {category, code, title, reference_info} objects. "
        "CSV: columns category, code, title, reference_info. Max 25MB.",
    )
    set_default = forms.BooleanField(
        required=False, label="Use as the default template for new engagement checklists",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_IMPORT_FILE_SIZE:
            raise forms.ValidationError(
                f"File is too large ({uploaded.size // 1024 // 1024}MB) — max {MAX_IMPORT_FILE_SIZE // 1024 // 1024}MB."
            )
        return uploaded


class ChecklistItemForm(forms.Form):
    status = forms.ChoiceField(choices=ChecklistItem.Status.choices)
    blocked_reason = forms.CharField(
        required=False, max_length=500, label="Why couldn't this be tested?",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Shown in the report's coverage section as a testing limitation.",
    )
    scope_tested = forms.CharField(
        required=False, max_length=5000, label="What was tested",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "GET /search?q\nPOST /api/orders (id)"}),
        help_text="One endpoint, URL or parameter per line. Used as Affects when you raise a finding from this check.",
    )
    reference_info = RichTextField(required=False)
    test_results = RichTextField(required=False)
    findings = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label="Linked findings", widget=forms.CheckboxSelectMultiple,
    )
    assignee = forms.ModelChoiceField(queryset=None, required=False, label="Assigned to", empty_label="Unassigned")

    def __init__(self, *args, engagement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["findings"].queryset = engagement.findings.all() if engagement else None
        # Only people who can open the engagement can own one of its checks.
        self.fields["assignee"].queryset = users_with_access(engagement) if engagement else None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == ChecklistItem.Status.BLOCKED:
            if not (cleaned.get("blocked_reason") or "").strip():
                self.add_error("blocked_reason", "Say why this check couldn't be tested.")
        else:
            cleaned["blocked_reason"] = ""
        return cleaned


class ChecklistCommentForm(forms.Form):
    body = RichTextField(required=True)
