from django import template
from django.utils.safestring import mark_safe

from ..google_fonts import font_face_css
from ..models import ReportProfile

register = template.Library()

_FALLBACK_SANS = "Plus Jakarta Sans"
_FALLBACK_MONO = "JetBrains Mono"
_SANS_TAIL = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif'
_MONO_TAIL = 'ui-monospace, "SF Mono", "Cascadia Code", monospace'


def _css_string_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


@register.simple_tag
def report_font_theme_style():
    """Override the app's --font-sans/--font-mono with the instance default Report
    Profile's fonts, when it has any that differ from the hardcoded fallback pair.

    Deliberately looks up only the true default profile (is_default=True), not
    "any profile" — an instance with report profiles but no default shouldn't have
    an arbitrary one dictate the whole app's typography. DB-read-only: never
    fetches over the network, so this can safely run on every page load.
    """
    profile = ReportProfile.objects.filter(is_default=True).first()
    body_font = (profile.body_font if profile else "") or _FALLBACK_SANS
    monospace_font = (profile.monospace_font if profile else "") or _FALLBACK_MONO

    faces = []
    overrides = []
    if body_font != _FALLBACK_SANS:
        faces.append(font_face_css(body_font))
        overrides.append(f'--font-sans: "{_css_string_escape(body_font)}", "{_FALLBACK_SANS}", {_SANS_TAIL};')
    if monospace_font != _FALLBACK_MONO:
        faces.append(font_face_css(monospace_font))
        overrides.append(f'--font-mono: "{_css_string_escape(monospace_font)}", "{_FALLBACK_MONO}", {_MONO_TAIL};')

    if not overrides:
        return ""
    css = "".join(faces) + ":root { " + " ".join(overrides) + " }"
    return mark_safe(f"<style>{css}</style>")
