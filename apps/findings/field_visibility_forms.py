from django import forms
from django.forms import BaseModelFormSet, modelformset_factory

from .models import ContentSectionDefinition

_BOOLEAN_FIELDS = [
    "is_active", "supports_image_upload", "portal_visible",
    "include_in_remediation_report_only", "is_import_target",
]


class ContentSectionCreateForm(forms.ModelForm):
    class Meta:
        model = ContentSectionDefinition
        fields = ["label"] + _BOOLEAN_FIELDS


class BaseContentSectionFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        ticked = [
            form for form in self.forms
            if form.is_valid() and form.cleaned_data.get("is_import_target")
        ]
        for form in [f for f in ticked if f.instance.is_protected]:
            # Scan import already fills Affected Assets from each result's
            # host/URL; the details text can't go there.
            form.add_error("is_import_target", "This built-in section can't be the scan import target.")
            ticked.remove(form)


ContentSectionDefinitionFormSet = modelformset_factory(
    ContentSectionDefinition,
    formset=BaseContentSectionFormSet,
    fields=["label"] + _BOOLEAN_FIELDS,
    widgets={"label": forms.TextInput(attrs={"aria-label": "Section name"})},
    extra=0,
)
