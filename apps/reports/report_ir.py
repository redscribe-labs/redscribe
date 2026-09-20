from dataclasses import dataclass, field
from typing import Union


@dataclass
class RichTextBlock:
    html: str


@dataclass
class StyledText:
    text: str
    background_rgba: str = ""


@dataclass
class TableBlock:
    columns: list[str]
    rows: list[list[Union[str, StyledText, "Block"]]]
    header_column: bool = False


@dataclass
class ListBlock:
    items: list[str]
    ordered: bool = False


@dataclass
class ImageBlock:
    src: str
    alt: str = ""
    caption: str = ""


@dataclass
class CodeBlock:
    text: str
    language: str = ""


@dataclass
class SeverityBar:
    label: str
    value: int
    color_rgba: str


@dataclass
class BarGraphBlock:
    series: list[SeverityBar]
    fallback: TableBlock


@dataclass
class CoverPageBlock:
    """Marker block — rendered from ReportMeta wherever {{ cover_page }} sits in the template."""


@dataclass
class TableOfContentsBlock:
    """Marker block — rendered from the document's own sections wherever {{ table_of_contents }} sits."""


Block = Union[
    RichTextBlock, TableBlock, ListBlock, ImageBlock, CodeBlock, BarGraphBlock,
    CoverPageBlock, TableOfContentsBlock,
]


@dataclass
class Section:
    key: str
    title: str
    blocks: list[Block] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)
    numbered: bool = True
    toc_entry: bool = False
    number: str = ""
    page_break_before: bool = False


@dataclass
class ReportMeta:
    project_id: str
    client_name: str
    test_type_label: str
    classification_label: str
    report_date: str
    is_remediation_report: bool = False
    firm_name: str = ""
    firm_logo_data_uri: str = ""
    cover_title: str = ""
    body_font: str = ""
    monospace_font: str = ""
    bullet_character: str = ""
    table_header_color: str = ""
    empty_cell_background_color: str = ""
    toc_heading: str = "Table of Contents"


@dataclass
class ReportDocument:
    meta: ReportMeta
    sections: list[Section] = field(default_factory=list)


def assign_numbers(document: ReportDocument) -> None:
    # An unnumbered section (numbered=False — an anonymous template-parse
    # wrapper, or a finding/observation subsection) is invisible for
    # numbering purposes: its numbered children continue the SAME counter
    # as their siblings at this level, rather than each such wrapper
    # silently restarting its own children at "1". Multiple separate
    # wrappers used to each reset to a fresh counter=0, so e.g. two
    # unrelated un-headed tag placements' children both ended up "1"
    # instead of counting 1, 2, 3, 4 across the whole level.
    def walk(sections: list[Section], prefix: str, counter: int) -> int:
        for section in sections:
            if section.numbered:
                counter += 1
                section.number = f"{prefix}{counter}"
                walk(section.children, f"{section.number}.", 0)
            else:
                section.number = ""
                counter = walk(section.children, prefix, counter)
        return counter

    walk(document.sections, "", 0)
