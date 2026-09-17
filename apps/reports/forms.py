from django import forms

ALLOWED_LOGO_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


class FirmBrandingForm(forms.Form):
    firm_name = forms.CharField(
        max_length=255, required=False, label="Company name",
        help_text="Shown in the sidebar, the login page, and every report's cover page — "
        "wherever the app would otherwise show its own \"RedScribe\" branding. "
        "The logo below takes priority over this when both are set.",
    )
    logo = forms.ImageField(
        required=False, label="Logo",
        help_text="PNG, JPEG, or WebP. Max 2MB.",
    )
    remove_logo = forms.BooleanField(required=False, label="Remove current logo")

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            content_type = getattr(logo, "content_type", None)
            if content_type not in ALLOWED_LOGO_CONTENT_TYPES:
                raise forms.ValidationError("Logo must be a PNG, JPEG, or WebP image.")
            if logo.size > MAX_LOGO_BYTES:
                raise forms.ValidationError(
                    f"Logo is too large ({logo.size // 1024}KB) — max {MAX_LOGO_BYTES // 1024}KB."
                )
        return logo


class ExportLimitsForm(forms.Form):
    max_concurrent_report_jobs = forms.IntegerField(
        required=False, min_value=1, max_value=50, label="Max simultaneous report exports",
        help_text="Caps how many PDF/Markdown/HTML exports may render at once, across the whole app, "
                   "so a burst of exports can't overload the server. Requests beyond this limit are asked to retry. "
                   "Left blank, the current value is kept.",
    )
