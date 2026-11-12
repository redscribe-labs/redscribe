import re

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_placeholders(text: str, context: dict) -> str:
    def replace(match):
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return _TOKEN_RE.sub(replace, text or "")


def _scope_summary(engagement) -> str:
    """Flat text rendering of the structured scope (replaces the old free-text
    Engagement.scope) so the {{ scope }} token keeps working in profiles/DOCX."""
    lines = []
    for category in engagement.asset_categories.prefetch_related("assets").all():
        assets = list(category.assets.all())
        if not assets:
            continue
        lines.append(f"{category.name}:")
        lines.extend(f"  {a.value}" for a in assets)
    return "\n".join(lines)


def build_placeholder_context(*, engagement, user) -> dict:
    from django.utils import timezone

    return {
        "client_name": engagement.client_name,
        "reference_number": engagement.reference_number,
        "scope": _scope_summary(engagement),
        "start_date": engagement.start_date.isoformat() if engagement.start_date else "",
        "end_date": engagement.end_date.isoformat() if engagement.end_date else "",
        "report_date": timezone.localdate().isoformat(),
        "prepared_by": str(user) if user else "",
    }
