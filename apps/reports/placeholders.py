import re

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_placeholders(text: str, context: dict) -> str:
    def replace(match):
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return _TOKEN_RE.sub(replace, text or "")


def build_placeholder_context(*, engagement, user) -> dict:
    from django.utils import timezone

    return {
        "client_name": engagement.client_name,
        "reference_number": engagement.reference_number,
        "scope": engagement.scope,
        "start_date": engagement.start_date.isoformat() if engagement.start_date else "",
        "end_date": engagement.end_date.isoformat() if engagement.end_date else "",
        "report_date": timezone.localdate().isoformat(),
        "prepared_by": str(user) if user else "",
    }
