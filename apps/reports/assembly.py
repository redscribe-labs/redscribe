import base64
import json
from dataclasses import dataclass
from html import escape

from apps.checklist.models import ChecklistItem
from apps.findings.display_id import assign_display_ids
from apps.findings.models import ContentSectionDefinition, Finding
from apps.findings.scan_import import FORMAT_LABELS

from .block_registry import BLOCK_REGISTRY, BlockContext
from .labels import get_label, get_severity_label, get_status_label
from .models import ReportProfile, ReportSettings, ReportTextBlockDefinition
from .placeholders import _TOKEN_RE, build_placeholder_context, render_placeholders
from .report_ir import (
    BarGraphBlock,
    ListBlock,
    ReportDocument,
    ReportMeta,
    RichTextBlock,
    Section,
    SeverityBar,
    StyledText,
    TableBlock,
    assign_numbers,
)
from .services import PUBLISHABLE_STATUSES, _make_image_resolver, _render_finding
from .tiptap_render import _render_node, tiptap_to_html

_DEFAULT_SEVERITY_COLORS = {
    Finding.Severity.CRITICAL: {"open": "rgba(183,28,28,1)", "closed": "rgba(183,28,28,0.35)"},
    Finding.Severity.HIGH: {"open": "rgba(244,67,54,1)", "closed": "rgba(244,67,54,0.35)"},
    Finding.Severity.MEDIUM: {"open": "rgba(255,152,0,1)", "closed": "rgba(255,152,0,0.35)"},
    Finding.Severity.LOW: {"open": "rgba(76,175,80,1)", "closed": "rgba(76,175,80,0.35)"},
    Finding.Severity.INFORMATIONAL: {"open": "rgba(27,94,32,1)", "closed": "rgba(27,94,32,0.35)"},
}

_SEVERITY_ORDER = [
    Finding.Severity.CRITICAL,
    Finding.Severity.HIGH,
    Finding.Severity.MEDIUM,
    Finding.Severity.LOW,
    Finding.Severity.INFORMATIONAL,
]


def get_draft_config(engagement):
    from django.db import IntegrityError, transaction

    from .models import ReportConfig

    try:
        with transaction.atomic():
            config, _ = ReportConfig.objects.get_or_create(
                engagement=engagement, is_template=False, defaults={"name": "Draft"}
            )
    except IntegrityError:
        config = ReportConfig.objects.get(engagement=engagement, is_template=False)
    return config


def sanitize_content(raw) -> dict:
    defaults = default_content()
    if not isinstance(raw, dict):
        return defaults
    result = {}
    for key, default_value in defaults.items():
        value = raw.get(key, default_value)
        if isinstance(default_value, dict):
            result[key] = value if isinstance(value, dict) else default_value
        elif isinstance(default_value, list):
            result[key] = value if isinstance(value, list) else default_value
        else:
            result[key] = value
    return result


def seeded_content(engagement, config) -> dict:
    content = sanitize_content(config.content)
    if content["findings"].get("included_ids") is None:
        publishable = [f for f in engagement.findings.all() if f.workflow_status in PUBLISHABLE_STATUSES]
        publishable.sort(key=lambda f: (
            _SEVERITY_ORDER.index(f.severity) if f.severity in _SEVERITY_ORDER else 99, f.created_at
        ))
        content["findings"]["included_ids"] = [str(f.id) for f in publishable]
    return content


def default_content() -> dict:
    return {
        "toggles": {"page_break_per_finding": False},
        "dynamic": {},
        "cover": {"title": "", "classification_label": ""},
        "breakdown": {
            "enabled": True, "show_chart": True, "show_table": True, "severities": None, "statuses": None,
            "intro": "", "notes": "",
        },
        "document_control": {"notes": ""},
        "observations": [],
        "testing_phases": [],
        "findings": {"included_ids": None, "severities": None, "statuses": None},
    }


def dynamic_tag_value(content: dict, slug: str, profile) -> str:
    dynamic = content.get("dynamic", {}) if isinstance(content, dict) else {}
    value = dynamic.get(slug)
    if value:
        return value
    if profile is not None and isinstance(profile.block_defaults, dict):
        return profile.block_defaults.get(slug, "")
    return ""


def _template_tag_order(template) -> dict[str, int]:
    order: dict[str, int] = {}
    nodes = template.get("content") if isinstance(template, dict) else None
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        tag = _placeholder_tag(node)
        if tag is not None and tag not in order:
            order[tag] = len(order)
    return order


def visible_dynamic_blocks(profile) -> list:
    if profile is None:
        return []
    order = _template_tag_order(profile.template)
    blocks = list(profile.text_blocks.filter(is_active=True))
    # Blocks the template doesn't (yet) place anywhere sort after the ones
    # that do, in the order they were placed — matches how they'd actually
    # appear in the built report rather than an alphabetical label sort
    # that has no relation to it.
    return sorted(blocks, key=lambda b: (order.get(b.slug, len(order)), b.label, b.id))


def _select_findings(engagement, findings_cfg: dict) -> list[Finding]:
    if not isinstance(findings_cfg, dict):
        findings_cfg = {}

    all_findings = list(
        engagement.findings.select_related("created_by").prefetch_related("classifications")
    )
    publishable = [f for f in all_findings if f.workflow_status in PUBLISHABLE_STATUSES]

    included_ids = findings_cfg.get("included_ids")
    if isinstance(included_ids, list):
        by_id = {str(f.id): f for f in publishable}
        return [by_id[i] for i in included_ids if isinstance(i, str) and i in by_id]

    severities = findings_cfg.get("severities")
    severities = severities if isinstance(severities, list) else None
    statuses = findings_cfg.get("statuses")
    statuses = statuses if isinstance(statuses, list) else None
    selected = [
        f for f in publishable
        if (severities is None or f.severity in severities)
        and (statuses is None or f.status in statuses)
    ]

    def sort_key(f):
        return (_SEVERITY_ORDER.index(f.severity) if f.severity in _SEVERITY_ORDER else 99, f.created_at)

    return sorted(selected, key=sort_key)


def _document_control_rows(engagement, profile: ReportProfile) -> list[list[str]]:
    import datetime

    rows = [
        [dict(engagement.Status.choices).get(h.status, h.status), h.changed_at.date().isoformat(),
         str(h.changed_by) if h.changed_by else "—"]
        for h in engagement.status_history.select_related("changed_by").all()
    ]
    rows.append([get_label(profile, "doc_control_report_exported"), datetime.date.today().isoformat(), "—"])
    return rows


def _document_control_table(engagement, profile: ReportProfile) -> TableBlock:
    return TableBlock(
        columns=[
            get_label(profile, "doc_control_col_stage"),
            get_label(profile, "doc_control_col_date"),
            get_label(profile, "doc_control_col_changed_by"),
        ],
        rows=_document_control_rows(engagement, profile),
    )


def _breakdown_counts(findings: list[Finding], profile: ReportProfile, options: dict | None = None):
    """Data-only core of the breakdown-of-findings block, shared by the IR
    builder below (wraps it in BarGraphBlock/TableBlock) and docx_export.py
    (wraps it in a real docx table — DOCX has no charting API, so there's
    no bar-graph equivalent there, table-only by design)."""
    options = options if isinstance(options, dict) else {}
    severities = options.get("severities") or list(_SEVERITY_ORDER)
    statuses = options.get("statuses") or [Finding.Status.OPEN, Finding.Status.CLOSED]
    filtered = [f for f in findings if f.severity in severities and f.status in statuses]

    colors = profile.severity_colors or {}
    rows = []
    for severity in _SEVERITY_ORDER:
        if severity not in severities:
            continue
        open_count = sum(1 for f in filtered if f.severity == severity and f.status == Finding.Status.OPEN)
        closed_count = sum(1 for f in filtered if f.severity == severity and f.status == Finding.Status.CLOSED)
        defaults = _DEFAULT_SEVERITY_COLORS[severity]
        # Same "unconfigured falls back to the built-in default" contract
        # as _severity_status_color (via colors.severity_rgba) — a report
        # profile that's never touched severity_colors still gets sensible
        # per-severity colors here, not an empty/neutral one.
        open_color = (colors.get(severity) or {}).get("open") or defaults["open"]
        closed_color = (colors.get(severity) or {}).get("closed") or defaults["closed"]
        rows.append({
            "label": get_severity_label(profile, severity),
            "open_count": open_count, "closed_count": closed_count,
            "open_color": open_color, "closed_color": closed_color,
        })
    return filtered, severities, statuses, rows


def _breakdown_section(
    findings: list[Finding], profile: ReportProfile, options: dict | None = None,
    notes_html: str = "", intro_html: str = "",
) -> Section | None:
    options = options if isinstance(options, dict) else {}
    if options.get("enabled") is False:
        return None
    show_chart = options.get("show_chart", True)
    show_table = options.get("show_table", True)
    if not show_chart and not show_table:
        return None
    filtered, severities, statuses, count_rows = _breakdown_counts(findings, profile, options)

    series = []
    fallback_rows = []
    open_label = get_status_label(profile, "OPEN")
    closed_label = get_status_label(profile, "CLOSED")
    for row in count_rows:
        if Finding.Status.OPEN in statuses:
            series.append(SeverityBar(f"{row['label']} ({open_label})", row["open_count"], row["open_color"]))
        if Finding.Status.CLOSED in statuses and row["closed_count"]:
            series.append(SeverityBar(f"{row['label']} ({closed_label})", row["closed_count"], row["closed_color"]))
        fallback_rows.append([row["label"], str(row["open_count"]), str(row["closed_count"])])

    blocks = []
    # Sits above the chart — first thing in the block regardless of
    # show_chart/show_table, since it's meant to introduce the whole
    # breakdown rather than comment on any one part of it.
    if intro_html:
        blocks.append(RichTextBlock(intro_html))
    if show_chart:
        fallback = TableBlock(
            columns=[get_label(profile, "vuln_table_col_severity"), open_label, closed_label], rows=fallback_rows,
        )
        blocks.append(BarGraphBlock(series=series, fallback=fallback))
    # Sits between the chart and the table in document order — blocks
    # render fully before children (see ir_render._render_section), and
    # the vulnerabilities table below is a child section, so appending
    # here is genuinely "between" regardless of which of chart/table are
    # actually shown.
    if notes_html:
        blocks.append(RichTextBlock(notes_html))

    children = []
    if show_table:
        vuln_table = TableBlock(
            columns=[
                get_label(profile, "vuln_table_col_id"),
                get_label(profile, "vuln_table_col_severity"),
                get_label(profile, "vuln_table_col_title"),
                get_label(profile, "vuln_table_col_status"),
            ],
            rows=[
                [
                    f.display_id,
                    StyledText(get_severity_label(profile, f.severity), background_rgba=_severity_status_color(f, profile)),
                    f.title,
                    StyledText(get_status_label(profile, f.status), background_rgba=_severity_status_color(f, profile)),
                ]
                for f in filtered
            ],
        )
        # No heading — this table sits immediately under the chart/notes
        # above (both already establish the "breakdown of findings"
        # context), so a "Vulnerabilities table" heading here just read as
        # a redundant, unwanted subsection title rather than a real
        # structural break. numbered=False since with no title there's
        # nothing for a section number to label.
        children.append(Section(key="vulnerabilities_table", title="", numbered=False, blocks=[vuln_table]))

    return Section(
        key="breakdown_of_findings",
        title="Breakdown of findings",
        blocks=blocks,
        children=children,
    )


def _severity_status_color(finding: Finding, profile: ReportProfile) -> str:
    from .colors import severity_rgba

    variant = "open" if finding.status == Finding.Status.OPEN else "closed"
    return severity_rgba(finding.severity, variant, profile)


def _finding_metadata_table(finding: Finding, profile: ReportProfile) -> TableBlock | ListBlock:
    color = _severity_status_color(finding, profile)
    severity_label = get_severity_label(profile, finding.severity)
    status_label = get_status_label(profile, finding.status)
    rows = [
        [get_label(profile, "finding_severity_rating"), StyledText(severity_label, background_rgba=color)],
        [get_label(profile, "finding_id_row"), finding.display_id],
        [get_label(profile, "finding_cvss_score"), finding.cvss_score or "—"],
        [get_label(profile, "finding_cvss_vector"), finding.cvss_vector or "—"],
        [get_label(profile, "finding_cve_id"), finding.cve_id or "—"],
    ]
    tags = list(finding.classifications.all())
    if tags:
        rows += [[tag.taxonomy, tag.value] for tag in tags]
    else:
        rows.append([get_label(profile, "finding_classification"), "—"])
    rows.append([get_label(profile, "finding_status"), StyledText(status_label, background_rgba=color)])

    if profile.finding_table_layout == ReportProfile.FindingTableLayout.LIST:
        # Colored severity/status cells have no list equivalent — the color
        # is a table-cell affordance, so it's dropped here in favor of the
        # plain "label: value" text every ListBlock renderer already knows
        # how to draw (HTML/PDF/Markdown alike).
        return ListBlock(items=[
            f"{label}: {value.text if isinstance(value, StyledText) else value}" for label, value in rows
        ])
    return TableBlock(columns=["", ""], header_column=True, rows=rows)


def _finding_section(
    finding: Finding, rendered, is_remediation_report: bool, profile: ReportProfile,
    sections: list, *, page_break_before: bool = False,
) -> Section:
    # "Affects" is backed by finding.affects_list rather than generic
    # FindingSection content, but its ContentSectionDefinition row (slug
    # "affects", is_protected=True — see migration 0021) carries a real
    # "order" like any other section, so it slots into the loop below at
    # whatever position the admin configured on the Finding Structure page.
    children = []

    for definition in sections:
        if definition.include_in_remediation_report_only and not is_remediation_report:
            continue
        if definition.slug == "affects":
            children.append(Section(
                key=f"finding:{finding.id}:affects", title=definition.label,
                numbered=False, blocks=[ListBlock(items=rendered.affects_list)],
            ))
            continue
        html = rendered.section_html.get(definition.slug)
        if not html:
            continue
        children.append(Section(
            key=f"finding:{finding.id}:{definition.slug}", title=definition.label,
            numbered=False, blocks=[RichTextBlock(html)],
        ))

    if is_remediation_report and rendered.retest_records:
        remediation_children = [
            Section(
                key=f"finding:{finding.id}:retest_history:notes:{i}",
                title=f"Retest notes — {r['date']} ({r['status_display']})",
                numbered=False, blocks=[RichTextBlock(r["notes_html"])],
            )
            for i, r in enumerate(rendered.retest_records) if r["notes_html"]
        ]
        children.append(Section(
            key=f"finding:{finding.id}:retest_history", title=get_label(profile, "retest_history"),
            numbered=False,
            blocks=[TableBlock(
                columns=[
                    get_label(profile, "retest_col_date"),
                    get_label(profile, "retest_col_tested_by"),
                    get_label(profile, "retest_col_result"),
                ],
                rows=[[r["date"], r["tested_by"], r["status_display"]] for r in rendered.retest_records],
            )],
            children=remediation_children,
        ))
    return Section(
        key=f"finding:{finding.id}",
        title=finding.title,
        blocks=[_finding_metadata_table(finding, profile)],
        children=children,
        page_break_before=page_break_before,
    )


def _assessment_team_data(engagement) -> list[dict]:
    # Sourced from actual EngagementMembership records — not
    # apps.engagements.access.users_with_access, which answers "who may
    # view this engagement" (all superadmins, plus anyone with the blanket
    # engagements.view_all permission) rather than "who worked on it". Using
    # that access helper here leaked management-only accounts (e.g.
    # superadmin) into the report even though they were never assigned.
    members = (
        engagement.memberships.select_related("user", "user__role").order_by("user__username")
    )
    return [
        {
            "member": membership.user, "role_name": membership.user.role.name,
            "background": membership.user.background,
            "qualifications": membership.user.qualifications,
        }
        for membership in members
    ]


def _assessment_team_section(engagement, profile: ReportProfile) -> Section | None:
    data = _assessment_team_data(engagement)
    if not data:
        return None

    children = []
    for entry in data:
        member = entry["member"]
        blocks = []
        background_html = tiptap_to_html(entry["background"])
        if background_html:
            blocks.append(RichTextBlock(background_html))
        qualifications_html = tiptap_to_html(entry["qualifications"])
        if qualifications_html:
            blocks.append(RichTextBlock(qualifications_html))
        children.append(Section(
            key=f"team:{member.uuid}", title=f"{member} — {entry['role_name']}",
            numbered=False, blocks=blocks,
        ))
    return Section(key="assessment_team", title=get_label(profile, "assessment_team"), children=children)


def _checklist_coverage_data(engagement, display_id_lookup: dict) -> list[dict]:
    status_labels = dict(ChecklistItem.Status.choices)
    data = []
    for run in engagement.checklist_runs.prefetch_related("items__findings").all():
        categories: dict[str, list] = {}
        for item in run.items.all():
            categories.setdefault(item.category, []).append(item)

        category_rows = []
        for category, items in categories.items():
            rows = []
            for item in items:
                linked = list(item.findings.all())
                if linked:
                    linked_display = ", ".join(display_id_lookup.get(f.id, f.title) for f in linked)
                else:
                    linked_display = "—"
                rows.append([item.code or "—", item.title, status_labels.get(item.status, item.status), linked_display])
            category_rows.append({"category": category or "Uncategorized", "rows": rows})

        data.append({"run_id": run.id, "run_label": run.label, "categories": category_rows})
    return data


def _checklist_coverage_section(engagement, display_id_lookup: dict, profile: ReportProfile) -> Section:
    coverage_title = get_label(profile, "testing_methodology_coverage")
    data = _checklist_coverage_data(engagement, display_id_lookup)
    if not data:
        return Section(
            key="checklist_coverage", title=coverage_title,
            blocks=[RichTextBlock("<p>No checklist runs have been recorded for this engagement.</p>")],
        )

    run_children = []
    for run_data in data:
        category_children = [
            Section(
                key=f"checklist_run:{run_data['run_id']}:category:{cat['category']}", title=cat["category"],
                numbered=False,
                blocks=[TableBlock(
                    columns=[
                        get_label(profile, "checklist_col_code"),
                        get_label(profile, "checklist_col_item"),
                        get_label(profile, "checklist_col_status"),
                        get_label(profile, "checklist_col_linked_findings"),
                    ],
                    rows=cat["rows"],
                )],
            )
            for cat in run_data["categories"]
        ]
        run_children.append(Section(
            key=f"checklist_run:{run_data['run_id']}", title=run_data["run_label"],
            numbered=False, children=category_children,
        ))

    return Section(key="checklist_coverage", title=coverage_title, children=run_children)


def _scan_imports_data(engagement) -> list[dict]:
    records = engagement.scan_imports.select_related("imported_by").all()
    rows = []
    for record in records:
        if record.imported_by:
            imported_by = record.imported_by.get_full_name() or record.imported_by.username
        else:
            imported_by = "—"
        rows.append({
            "tool": FORMAT_LABELS.get(record.source_format, record.source_format),
            "filename": record.filename or "—",
            "imported_at": record.imported_at.strftime("%Y-%m-%d"),
            "imported_by": imported_by,
            "findings_created": record.findings_created,
        })
    return rows


def _scan_imports_section(engagement, profile: ReportProfile) -> Section:
    title = get_label(profile, "scan_imports")
    data = _scan_imports_data(engagement)
    if not data:
        return Section(
            key="scan_imports", title=title,
            blocks=[RichTextBlock("<p>No scanner imports have been recorded for this engagement.</p>")],
        )
    return Section(
        key="scan_imports", title=title,
        blocks=[TableBlock(
            columns=[
                get_label(profile, "scan_imports_col_tool"),
                get_label(profile, "scan_imports_col_filename"),
                get_label(profile, "scan_imports_col_date"),
                get_label(profile, "scan_imports_col_imported_by"),
                get_label(profile, "scan_imports_col_findings"),
            ],
            rows=[
                [row["tool"], row["filename"], row["imported_at"], row["imported_by"], str(row["findings_created"])]
                for row in data
            ],
        )],
    )


def _dict_rows(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def build_report_document(*, config, engagement, project_key, user) -> ReportDocument:
    settings_obj = ReportSettings.get_solo()
    profile = get_effective_profile(config) or ReportProfile()
    content = sanitize_content(config.content)
    toggles = content["toggles"]

    placeholder_context = build_placeholder_context(engagement=engagement, user=user)

    def substitute(text):
        return render_placeholders(text, placeholder_context)

    findings = _select_findings(engagement, content.get("findings", {}))
    assign_display_ids(findings, prefix=profile.finding_id_prefix or "F")
    image_resolver = _make_image_resolver(engagement, project_key)
    active_sections = list(ContentSectionDefinition.objects.filter(is_active=True))
    rendered_findings = {
        f.id: _render_finding(f, project_key, image_resolver, sections=active_sections, text_transform=substitute)
        for f in findings
    }

    import datetime

    firm_logo_data_uri = ""
    if settings_obj.firm_logo:
        firm_logo_data_uri = (
            f"data:{settings_obj.firm_logo_content_type};base64,"
            f"{base64.b64encode(bytes(settings_obj.firm_logo)).decode('ascii')}"
        )

    cover_overrides = content.get("cover") if isinstance(content.get("cover"), dict) else {}
    meta = ReportMeta(
        project_id=engagement.reference_number,
        client_name=engagement.client_name,
        test_type_label=engagement.get_test_type_display() if engagement.test_type else "",
        classification_label=cover_overrides.get("classification_label") or profile.classification_label,
        report_date=datetime.date.today().isoformat(),
        is_remediation_report=config.is_remediation_report,
        firm_name=settings_obj.firm_name,
        firm_logo_data_uri=firm_logo_data_uri,
        cover_title=substitute(cover_overrides.get("title") or profile.cover_title),
        body_font=profile.body_font,
        monospace_font=profile.monospace_font,
        bullet_character=profile.bullet_character,
        table_header_color=profile.table_header_color,
        empty_cell_background_color=profile.empty_cell_background_color,
        toc_heading=get_label(profile, "toc_heading"),
    )

    block_context = BlockContext(
        engagement=engagement, profile=profile, content=content, findings=findings,
        rendered_findings=rendered_findings, image_resolver=image_resolver, toggles=toggles,
        is_remediation_report=config.is_remediation_report,
        finding_section_builder=_make_finding_section_builder(config.is_remediation_report, profile, active_sections),
        breakdown_builder=_breakdown_section,
        document_control_builder=_document_control_table,
        assessment_team_builder=_assessment_team_section,
        dict_rows=_dict_rows,
        checklist_builder=_checklist_coverage_section,
        scan_imports_builder=_scan_imports_section,
        substitute=substitute,
    )

    document_sections = _parse_template(
        profile.template, block_context, content, profile, substitute=substitute,
    )

    document = ReportDocument(meta=meta, sections=document_sections)
    assign_numbers(document)
    return document


def _make_finding_section_builder(is_remediation_report: bool, profile: ReportProfile, active_sections: list):
    def build(finding, rendered, *, page_break_before=False):
        return _finding_section(
            finding, rendered, is_remediation_report, profile, active_sections,
            page_break_before=page_break_before,
        )
    return build


def get_effective_profile(config) -> "ReportProfile | None":
    profile = getattr(config, "profile", None)
    if profile is not None:
        return profile
    profile_id = getattr(config, "profile_id", None)
    if profile_id:
        return ReportProfile.objects.filter(pk=profile_id).first()
    return ReportProfile.objects.filter(is_default=True).first()


def _heading_text(node: dict) -> str:
    return "".join(
        c.get("text", "") for c in (node.get("content") or []) if c.get("type") == "text"
    ).strip()


def _placeholder_tag(node: dict) -> str | None:
    if node.get("type") != "paragraph":
        return None
    text = "".join(c.get("text", "") for c in (node.get("content") or []) if c.get("type") == "text").strip()
    match = _TOKEN_RE.fullmatch(text)
    return match.group(1) if match else None


def _resolve_custom_tag_nodes(slug: str, context: BlockContext, content: dict, profile) -> "list | str | None":
    if profile is None:
        return None
    definition = ReportTextBlockDefinition.objects.filter(profile=profile, slug=slug, is_active=True).first()
    if definition is None:
        return None
    if definition.include_in_remediation_report_only and not context.is_remediation_report:
        return None
    raw = dynamic_tag_value(content, slug, profile)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed.get("content") or []
    # Not valid Tiptap JSON — fall back to the old flat-HTML path so
    # malformed/legacy stored content still renders as plain text instead
    # of silently disappearing.
    return tiptap_to_html(raw, image_resolver=context.image_resolver, text_transform=context.substitute) or None


def _parse_template(
    template: dict, context: BlockContext, content: dict, profile, *, substitute,
) -> list:
    top_sections: list[Section] = []
    stack: list[tuple[int, Section]] = []
    counter = 0

    def current() -> "Section | None":
        return stack[-1][1] if stack else None

    def place(*, blocks=None, children=None):
        target = current()
        if target is None:
            nonlocal counter
            counter += 1
            target = Section(key=f"tpl:implicit:{counter}", title="", numbered=False)
            top_sections.append(target)
        if blocks:
            target.blocks.extend(blocks)
        if children:
            target.children.extend(children)

    def process_nodes(nodes, *, allow_tags):
        nonlocal counter
        for node in nodes or []:
            if not isinstance(node, dict):
                continue

            if node.get("type") == "heading":
                level = (node.get("attrs") or {}).get("level", 1)
                counter += 1
                section = Section(key=f"tpl:{counter}", title=_heading_text(node) or get_label(profile, "untitled_section"))
                section.toc_entry = level <= 2
                while stack and stack[-1][0] >= level:
                    stack.pop()
                if stack:
                    stack[-1][1].children.append(section)
                else:
                    top_sections.append(section)
                stack.append((level, section))
                continue

            # allow_tags is False while processing a resolved text block's
            # OWN content: a heading in there still gets spliced into this
            # SAME walk (sharing the same stack, not a separate one) so it
            # nests exactly as if typed directly into the template at this
            # point — an H3 lands under whatever H1/H2 is currently open
            # (real "1.1.3"-style numbering), not as a same-level sibling
            # of the tag that placed it. But a {{ tag }}-shaped paragraph
            # INSIDE that content is left as inert literal text, same as
            # always — text blocks have never supported nested tag
            # substitution, and adding that here would risk turning
            # previously-inert text (e.g. in a disclaimer explaining
            # placeholder syntax) into a live substitution.
            tag = _placeholder_tag(node) if allow_tags else None
            if tag is not None:
                if tag in BLOCK_REGISTRY:
                    fragment = BLOCK_REGISTRY[tag](context)
                    if fragment is not None:
                        place(blocks=fragment.blocks, children=fragment.children)
                else:
                    resolved = _resolve_custom_tag_nodes(tag, context, content, profile)
                    if isinstance(resolved, list):
                        process_nodes(resolved, allow_tags=False)
                    elif isinstance(resolved, str):
                        place(blocks=[RichTextBlock(resolved)])
                    else:
                        rendered = substitute(f"{{{{ {tag} }}}}")
                        if rendered != f"{{{{ {tag} }}}}":
                            place(blocks=[RichTextBlock(f"<p>{escape(rendered)}</p>")])
                continue

            html = _render_node(node, context.image_resolver, substitute)
            if html:
                place(blocks=[RichTextBlock(html)])

    process_nodes(template.get("content") if isinstance(template, dict) else None, allow_tags=True)
    return top_sections
