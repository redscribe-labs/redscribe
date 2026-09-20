import re

from django.core.exceptions import ValidationError

_RGBA_RE = re.compile(r"^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*[\d.]+\s*)?\)$")

_FONT_NAME_RE = re.compile(r"^[A-Za-z0-9 \-]{1,100}$")


def validate_rgba(value: str):
    if value and not _RGBA_RE.match(value.strip()):
        raise ValidationError('Expected an rgb()/rgba() color, e.g. "rgba(220,38,38,1)".')


def validate_font_name(value: str):
    if value and not _FONT_NAME_RE.match(value.strip()):
        raise ValidationError("Font names may only contain letters, digits, spaces, and hyphens.")


_MARKUP_CHARS = set("<>\"'\\{};")


def validate_no_markup_chars(value: str):
    if value and (bad := set(value) & _MARKUP_CHARS):
        raise ValidationError(f"May not contain: {' '.join(sorted(bad))}")
