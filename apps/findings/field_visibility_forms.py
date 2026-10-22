from django import forms
from django.forms import BaseModelFormSet, modelformset_factory

from .models import ContentSectionDefinition

_BOOLEAN_FIELDS = [
    "is_active", "supports_image_upload", "portal_visible",
    "include_in_remediation_report_only", "is_import_target",
]

# Scan import writes into a single section (the first ticked, in list order),
# so more than one tick would silently leave the others unused.
ONE_IMPORT_TARGET_ERROR = "Only one section can be the scan import target — untick all but one."


class ContentSectionCreateForm(forms.ModelForm):
    class Meta:
        model = ContentSectionDefinition
        fields = ["label"] + _BOOLEAN_FIELDS

    def clean_is_import_target(self):
        value = self.cleaned_data["is_import_target"]
        current = ContentSectionDefinition.objects.filter(is_import_target=True).first()
        if value and current is not None:
            raise forms.ValidationError(
                f"'{current.label}' is already the scan import target — untick it there first."
            )
        return value


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
        if len(ticked) > 1:
            for form in ticked:
                form.add_error("is_import_target", ONE_IMPORT_TARGET_ERROR)


ContentSectionDefinitionFormSet = modelformset_factory(
    ContentSectionDefinition,
    formset=BaseContentSectionFormSet,
    fields=["label"] + _BOOLEAN_FIELDS,
    extra=0,
)
