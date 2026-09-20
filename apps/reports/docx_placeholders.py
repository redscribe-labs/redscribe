"""Live-computed reference of every {{ tag }} currently valid in a Report
Profile's uploaded DOCX template. Finding-loop tags come from active
ContentSectionDefinition rows, which are fully admin-configurable and can
change at any time — so, like assembly.visible_dynamic_blocks, this must be
computed fresh on every page load, not hardcoded documentation."""
from apps.findings.models import ContentSectionDefinition

from .models import PLACEHOLDER_HELP

# Plain-value tags available anywhere in the template (outside the finding
# loop), beyond the shared engagement-metadata ones in PLACEHOLDER_HELP.
_DOCX_TOP_LEVEL_TAGS = [
    ("cover_title", "The report's cover title"),
    ("classification_label", "The profile's configured classification label"),
    ("firm_name", "Firm name (from Report Settings)"),
    ("test_type_label", "The engagement's test type (e.g. \"Web Application Penetration Test\"), or blank if unset"),
    ("reviewed_by", "The engagement's configured default reviewer, or blank if none set"),
    ("qa_by", "The engagement's configured default QA approver, or blank if none set"),
    ("approved_by", "The engagement's configured default approver, or blank if none set"),
]

# Rich-content tags available anywhere outside the finding loop — these use
# the {{p tag }} subdocument syntax, not plain {{ tag }}.
_DOCX_TOP_LEVEL_RICH_TAGS = [
    ("firm_logo", "Firm logo, as an embedded picture"),
    ("document_control", "Document control table (status history)"),
    ("assessment_team", "Assessment team members"),
    ("checklist_coverage", "Checklist coverage, grouped by run/category"),
    ("scan_imports", "Scanner imports appendix (tool, file, date, imported by, findings produced)"),
    ("breakdown_table", "Breakdown-of-findings severity/status counts table"),
]

# Loop variables available anywhere outside the finding loop — lists of
# {"title": <plain>, "content": <rich>} dicts, one per configured entry. Unlike the
# tags above, the template author writes the loop and controls layout entirely
# themselves (heading level, a table row, whatever) — see the guide for the pattern.
_DOCX_TOP_LEVEL_LOOP_TAGS = [
    ("observations", "Free-form per-engagement observations"),
    ("testing_phases", "Free-form per-engagement testing phases"),
]

# Plain-value tags available on each `finding` inside a
# {%p for finding in findings %} ... {%p endfor %} loop.
_FINDING_PLAIN_TAGS = [
    ("finding.id", "The finding's display ID (e.g. F001)"),
    ("finding.title", "Finding title"),
    ("finding.severity", "Severity label"),
    ("finding.status", "Status label (Open/Closed)"),
    ("finding.cvss_score", "CVSS score"),
    ("finding.cvss_vector", "CVSS vector"),
    ("finding.cve_id", "CVE ID, or — if unset"),
    ("finding.classifications", "List of classification tags"),
    ("finding.affects", "List of affected assets"),
]

_FINDING_RICH_TAGS = [
    ("finding.retest_history", "Retest history table (remediation reports only)"),
]


def available_top_level_tags(profile) -> list[tuple[str, str]]:
    return list(PLACEHOLDER_HELP) + _DOCX_TOP_LEVEL_TAGS


def available_top_level_rich_tags(profile) -> list[tuple[str, str]]:
    return list(_DOCX_TOP_LEVEL_RICH_TAGS)


def available_text_block_tags(profile) -> list[tuple[str, str]]:
    """This profile's own custom text blocks (ReportTextBlockDefinition) — profile-scoped
    and fully admin-configurable, so like the finding-section tags below, this must be
    computed live rather than hardcoded. Uses {{p tag }} subdocument syntax."""
    if profile is None or profile.pk is None:
        return []
    return [
        (definition.slug, definition.label)
        for definition in profile.text_blocks.filter(is_active=True).order_by("label")
    ]


def available_top_level_loop_tags(profile) -> list[tuple[str, str]]:
    return list(_DOCX_TOP_LEVEL_LOOP_TAGS)


def available_finding_tags(profile) -> list[tuple[str, str]]:
    return list(_FINDING_PLAIN_TAGS)


def _finding_attr(slug: str) -> str:
    # A ContentSectionDefinition slug commonly contains hyphens (Django's
    # SlugField default), but Jinja parses "finding.a-b" as subtraction,
    # not attribute access — bracket notation is the only syntax that's
    # safe for every possible slug, so it's what we document uniformly
    # rather than silently breaking on any hyphenated one.
    return f"finding['{slug}']" if not slug.isidentifier() else f"finding.{slug}"


def available_finding_rich_tags(profile) -> list[tuple[str, str]]:
    section_tags = [
        (_finding_attr(definition.slug), f"{definition.label} (rich text)")
        for definition in ContentSectionDefinition.objects.filter(is_active=True).narrative().order_by("order", "label")
    ]
    return section_tags + list(_FINDING_RICH_TAGS)
