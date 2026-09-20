from django import forms
from django.forms import modelformset_factory

from .models import ContentSectionDefinition

_BOOLEAN_FIELDS = [
    "is_active", "supports_image_upload", "portal_visible",
    "include_in_remediation_report_only", "is_import_target",
]


class ContentSectionCreateForm(forms.ModelForm):
    class Meta:
        model = ContentSectionDefinition
        fields = ["label"] + _BOOLEAN_FIELDS


ContentSectionDefinitionFormSet = modelformset_factory(
    ContentSectionDefinition,
    fields=["label"] + _BOOLEAN_FIELDS,
    extra=0,
)
