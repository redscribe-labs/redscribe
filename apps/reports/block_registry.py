from dataclasses import dataclass, field

from .models import ReportProfile
from .report_ir import CoverPageBlock, RichTextBlock, Section, TableOfContentsBlock
from .tiptap_render import tiptap_to_html


@dataclass
class BlockContext:
    engagement: object
    profile: ReportProfile
    content: dict
    findings: list
    rendered_findings: dict
    image_resolver: callable
    toggles: dict
    is_remediation_report: bool
    finding_section_builder: callable
    breakdown_builder: callable
    document_control_builder: callable
    assessment_team_builder: callable
    dict_rows: callable
    checklist_builder: callable
    scan_imports_builder: callable
    substitute: callable


@dataclass
class Fragment:
    blocks: list = field(default_factory=list)
    children: list = field(default_factory=list)


def _document_control(context: BlockContext) -> Fragment:
    notes = context.content.get("document_control", {}) if isinstance(context.content, dict) else {}
    notes_html = tiptap_to_html(
        (notes or {}).get("notes", ""), image_resolver=context.image_resolver, text_transform=context.substitute,
    )
    blocks = []
    if notes_html:
        blocks.append(RichTextBlock(notes_html))
    blocks.append(context.document_control_builder(context.engagement, context.profile))
    return Fragment(blocks=blocks)


def _cover_page(context: BlockContext) -> Fragment:
    return Fragment(blocks=[CoverPageBlock()])


def _table_of_contents(context: BlockContext) -> Fragment:
    return Fragment(blocks=[TableOfContentsBlock()])


def _breakdown_of_findings(context: BlockContext) -> Fragment | None:
    options = context.content.get("breakdown") if isinstance(context.content, dict) else None
    notes_html = tiptap_to_html(
        (options or {}).get("notes", ""), image_resolver=context.image_resolver, text_transform=context.substitute,
    )
    intro_html = tiptap_to_html(
        (options or {}).get("intro", ""), image_resolver=context.image_resolver, text_transform=context.substitute,
    )
    section = context.breakdown_builder(context.findings, context.profile, options, notes_html, intro_html)
    if section is None:
        return None
    return Fragment(blocks=section.blocks, children=section.children)


def _finding_details(context: BlockContext) -> Fragment:
    page_break = context.toggles.get("page_break_per_finding", False)
    children = [
        context.finding_section_builder(f, context.rendered_findings[f.id], page_break_before=page_break)
        for f in context.findings
    ]
    return Fragment(children=children)


def _observations(context: BlockContext) -> Fragment:
    # No toc_entry — same reasoning as findings (see assembly._finding_section):
    # one line per item doesn't scale to a report with many observations,
    # and the TOC is meant to list only real H1/H2 chapter/subsection
    # headings, not every repeating content item.
    observations = context.dict_rows(context.content.get("observations", []))
    children = [
        Section(
            key=f"observation:{i}", title=o.get("title", ""),
            blocks=[RichTextBlock(tiptap_to_html(
                o.get("content", ""), image_resolver=context.image_resolver, text_transform=context.substitute,
            ))],
        )
        for i, o in enumerate(observations)
    ]
    return Fragment(children=children)


def _testing_phases(context: BlockContext) -> Fragment:
    # No toc_entry — same reasoning as observations/findings above.
    phases = context.dict_rows(context.content.get("testing_phases", []))
    children = [
        Section(
            key=f"phase:{i}", title=p.get("title", ""),
            blocks=[RichTextBlock(tiptap_to_html(
                p.get("content", ""), image_resolver=context.image_resolver, text_transform=context.substitute,
            ))],
        )
        for i, p in enumerate(phases)
    ]
    return Fragment(children=children)


def _assessment_team(context: BlockContext) -> Fragment | None:
    section = context.assessment_team_builder(context.engagement, context.profile)
    if section is None:
        return None
    return Fragment(children=section.children)


def _checklist_coverage(context: BlockContext) -> Fragment:
    display_id_lookup = {f.id: f.display_id for f in context.findings}
    section = context.checklist_builder(context.engagement, display_id_lookup, context.profile)
    return Fragment(blocks=section.blocks, children=section.children)


def _scan_imports(context: BlockContext) -> Fragment:
    section = context.scan_imports_builder(context.engagement, context.profile)
    return Fragment(blocks=section.blocks, children=section.children)


BLOCK_REGISTRY = {
    "cover_page": _cover_page,
    "document_control": _document_control,
    "table_of_contents": _table_of_contents,
    "breakdown_of_findings": _breakdown_of_findings,
    "finding_details": _finding_details,
    "observations": _observations,
    "testing_phases": _testing_phases,
    "assessment_team": _assessment_team,
    "checklist_coverage": _checklist_coverage,
    "scan_imports": _scan_imports,
}
