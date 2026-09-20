from django import template
from django.utils.safestring import mark_safe

from ..colors import darken, mix_with_white
from ..models import ReportProfile

register = template.Library()


@register.simple_tag
def editor_code_theme_style():
    profile = ReportProfile.objects.filter(is_default=True).first() or ReportProfile.objects.first()
    table_header_color = (profile.table_header_color if profile else "") or "rgba(248,250,252,1)"
    code_bg = mix_with_white(table_header_color, 0.85)
    code_border = darken(table_header_color, 0.15)
    css = (
        ":root, .dark { --editor-code-bg: %s; --editor-code-border: %s; --editor-code-text: #1e293b; }"
        % (code_bg, code_border)
    )
    return mark_safe(f"<style>{css}</style>")
