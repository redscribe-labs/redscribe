from django import template

register = template.Library()

_BADGE_COLORS = {
    "IN_PROGRESS": "blue", "IN_REVIEW": "amber", "QA": "amber",
    "APPROVED": "green", "DELIVERED": "green",
    "AWAITING_REMEDIATION_TEST": "purple", "REMEDIATION_TEST": "purple", "CLOSED": "slate",
    "CRITICAL": "red", "HIGH": "orange", "MEDIUM": "amber", "LOW": "blue", "INFORMATIONAL": "slate",
    "OPEN": "red",
    "DRAFT": "slate", "REVIEWED": "blue", "REVIEW_CHANGES_REQUESTED": "amber",
    "QA_APPROVED": "green", "QA_CHANGES_REQUESTED": "amber",
    "PENDING": "amber", "REJECTED": "red",
    "NOT_TESTED": "slate", "TESTED_NO_FINDING": "green",
    "TESTED_FINDING_RAISED": "red", "NOT_APPLICABLE": "slate",
    "PENDING_QA": "amber",
    "NOT_RETESTED": "slate", "FIXED": "green", "NOT_FIXED": "red", "PARTIALLY_FIXED": "amber", "RISK_ACCEPTED": "purple",
    "superadmin": "purple", "team_lead": "blue", "senior": "green", "consultant": "slate", "client": "orange",
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
    from apps.reports.colors import contrasting_text_rgb, severity_rgba

    background = severity_rgba(severity_value, "open")
    r, g, b = contrasting_text_rgb(background)
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
