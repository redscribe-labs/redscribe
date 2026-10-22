from django import template
from django.utils.html import json_script as _json_script
from django.utils.safestring import mark_safe

register = template.Library()

# "blue" badges are drawn in the bell ramp (Brick Ember, a red), so nothing
# that isn't a warning maps to it. Severity itself is coloured from the report
# profile's palette (severity_*_style below), not from this table.
_BADGE_COLORS = {
    "IN_PROGRESS": "brand", "IN_REVIEW": "purple", "QA": "mist",
    "APPROVED": "green", "DELIVERED": "slate",
    "AWAITING_REMEDIATION_TEST": "amber", "REMEDIATION_TEST": "orange", "CLOSED": "slate",
    "CRITICAL": "red", "HIGH": "orange", "MEDIUM": "amber", "LOW": "mist", "INFORMATIONAL": "slate",
    "OPEN": "red",
    "DRAFT": "slate", "REVIEWED": "mist", "REVIEW_CHANGES_REQUESTED": "amber",
    "QA_APPROVED": "brand", "QA_CHANGES_REQUESTED": "amber",
    "PENDING": "amber", "REJECTED": "red",
    "NOT_TESTED": "slate", "TESTED_NO_FINDING": "green",
    "TESTED_FINDING_RAISED": "red", "NOT_APPLICABLE": "slate", "BLOCKED": "amber",
    "PENDING_QA": "amber",
    "NOT_RETESTED": "slate", "FIXED": "green", "NOT_FIXED": "red", "PARTIALLY_FIXED": "amber", "RISK_ACCEPTED": "purple",
    "superadmin": "purple", "team_lead": "brand", "senior": "green", "consultant": "slate", "client": "orange",
}


@register.filter(name="badge_class")
def badge_class(status_value):
    return f"badge-{_BADGE_COLORS.get(status_value, 'slate')}"


@register.filter(name="rail_class")
def rail_class(status_value):
    return f"rail-{_BADGE_COLORS.get(status_value, 'slate')}"


@register.filter(name="severity_style")
def severity_style(finding):
    from apps.reports.colors import finding_severity_style

    style = finding_severity_style(finding)
    return f"background-color:{style['background']};color:{style['color']};"


@register.filter(name="severity_rail_style")
def severity_rail_style(finding):
    from apps.reports.colors import severity_rgba

    color = severity_rgba(finding.severity, "open" if finding.status == finding.Status.OPEN else "closed")
    return f"border-left-color:{color};"


@register.filter(name="severity_value_rail_style")
def severity_value_rail_style(severity_value):
    from apps.reports.colors import severity_rgba

    color = severity_rgba(severity_value, "open")
    return f"border-left-color:{color};"


@register.filter(name="severity_chip_style")
def severity_chip_style(severity_value):
    from apps.reports.colors import accessible_text_rgb, severity_rgba

    background = severity_rgba(severity_value, "open")
    r, g, b = accessible_text_rgb(background)
    return f"background-color:{background};color:rgb({r},{g},{b});"


@register.filter(name="has_permission")
def has_permission(user, codename):
    return bool(user) and user.is_authenticated and user.has_permission(codename)


@register.filter(name="mfa_satisfied")
def mfa_satisfied(user, feature_flags):
    from apps.accounts.middleware import mfa_satisfied as _mfa_satisfied

    return _mfa_satisfied(user, feature_flags)


@register.filter(name="can_manage_engagement")
def can_manage_engagement(user, engagement):
    from apps.engagements.permissions import is_engagement_manager

    return is_engagement_manager(user, engagement)


@register.filter(name="initials")
def initials(user):
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    if first or last:
        return f"{first[:1]}{last[:1]}".upper()
    username = getattr(user, "username", str(user))
    if len(username) < 2:
        return username.upper()
    return f"{username[0]}{username[-1]}".upper()


@register.filter(name="add_class")
def add_class(bound_field, css_class):
    existing = bound_field.field.widget.attrs.get("class", "")
    merged = f"{existing} {css_class}".strip()
    return bound_field.as_widget(attrs={**bound_field.field.widget.attrs, "class": merged})


# Admin pages grouped under the sidebar's single "Settings" entry, in menu
# order: (permission, url name, label, group, path prefix the page lives under).
_SETTINGS_PAGES = [
    ("users.manage", "user_management:list", "Users", "People", "/user-management/"),
    ("roles.manage", "role_management:list", "Roles & permissions", "People", "/roles/"),
    ("clients.manage", "clients:list", "Clients", "People", "/clients/"),
    ("field_visibility.manage", "field_visibility:edit", "Finding structure", "Findings", "/field-visibility/"),
    ("feature_flags.manage", "feature_flags:edit", "Feature flags", "System", "/feature-flags/"),
    ("licensing.manage", "licensing:edit", "Licensing", "System", "/licensing/"),
    ("audit_log.manage", "audit:list", "Audit log", "System", "/audit/"),
]


@register.simple_tag
def settings_pages(user, path=""):
    from django.urls import reverse

    if not (user and user.is_authenticated):
        return []
    return [
        {"label": label, "url": reverse(url_name), "group": group, "active": (path or "").startswith(prefix)}
        for codename, url_name, label, group, prefix in _SETTINGS_PAGES
        if user.has_permission(codename)
    ]


@register.simple_tag
def settings_active(path):
    return any((path or "").startswith(prefix) for *_, prefix in _SETTINGS_PAGES)


@register.filter(name="status_stages")
def status_stages(engagement):
    """The engagement's status pipeline, each stage marked done/current/todo."""
    choices = list(type(engagement).Status.choices)
    values = [value for value, _ in choices]
    current = values.index(engagement.status) if engagement.status in values else -1
    return [
        {
            "value": value,
            "label": label,
            "state": "done" if i < current else ("current" if i == current else "todo"),
        }
        for i, (value, label) in enumerate(choices)
    ]


@register.filter(name="dict_get")
def dict_get(mapping, key):
    return (mapping or {}).get(key)


@register.simple_tag(takes_context=True)
def json_script_csp(context, value, element_id):
    """Like Django's ``json_script`` filter, but carries the per-request CSP
    nonce on the emitted ``<script type="application/json">`` tag. Django's
    builtin can't take a nonce, so under our nonce-based CSP (no
    ``'unsafe-inline'``) those data blocks are reported as script-src-elem
    violations in strict browsers. The JSON escaping is still Django's; we only
    insert the nonce attribute, whose value is URL-safe and so HTML-inert."""
    html = _json_script(value, element_id)
    request = context.get("request")
    nonce = getattr(request, "csp_nonce", "") if request is not None else ""
    if nonce:
        html = mark_safe(html.replace("<script", f'<script nonce="{nonce}"', 1))
    return html
