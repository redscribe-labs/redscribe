from django import forms

from .models import LicenseKey
from .verify import verify_license_key


class LicenseKeyForm(forms.ModelForm):
    class Meta:
        model = LicenseKey
        fields = ["key_text"]
        widgets = {
            "key_text": forms.Textarea(attrs={"rows": 3, "class": "field-input font-mono text-xs"}),
        }

    def clean_key_text(self):
        key_text = self.cleaned_data["key_text"].strip()
        if key_text and verify_license_key(key_text) is None:
            raise forms.ValidationError(
                "This doesn't look like a valid license key — check for missing/extra characters, "
                "or contact us if you believe this is a mistake."
            )
        return key_text
