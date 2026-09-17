import base64
import re
from html.parser import HTMLParser

from .report_ir import (
    BarGraphBlock,
    CodeBlock,
    CoverPageBlock,
    ImageBlock,
    ListBlock,
    ReportDocument,
    RichTextBlock,
    Section,
    StyledText,
    TableBlock,
    TableOfContentsBlock,
)

_EXT_BY_MIME = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
    "image/webp": "webp", "image/svg+xml": "svg",
}
_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.*)$", re.DOTALL)


class ImageCollector:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self._counter = 0

    def add(self, data_uri: str) -> str | None:
        match = _DATA_URI_RE.match(data_uri or "")
        if not match:
            return None
        mime, b64 = match.groups()
        ext = _EXT_BY_MIME.get(mime, "bin")
        try:
            content = base64.b64decode(b64)
        except (ValueError, TypeError):
            return None
        self._counter += 1
        filename = f"image{self._counter}.{ext}"
        self.files[filename] = content
        return f"images/{filename}"


class _Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag=None, attrs=None, text=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children: list["_Node"] = []
        self.text = text


class _TreeBuilder(HTMLParser):
    _VOID_TAGS = {"br", "hr", "img"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag=tag, attrs=attrs)
        self._stack[-1].children.append(node)
        if tag not in self._VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Node(tag=tag, attrs=attrs))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(_Node(text=data))


_INLINE_MARK_MD = {"strong": "**", "em": "_", "s": "~~", "mark": "=="}

_ALLOWED_LINK_PROTOCOLS = ("http://", "https://", "mailto:")


def _md_link_destination(href: str) -> str | None:
    if not href.lower().startswith(_ALLOWED_LINK_PROTOCOLS):
        return None
    escaped = href.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>")
    return f"<{escaped}>"


def _escape_html_breakout(text: str) -> str:
    return text.replace("<", "\\<").replace(">", "\\>")


def _render_inline(node: _Node, images: ImageCollector) -> str:
    if node.text is not None:
        return _escape_html_breakout(node.text)
    if node.tag in _INLINE_MARK_MD:
        wrap = _INLINE_MARK_MD[node.tag]
        inner = "".join(_render_inline(c, images) for c in node.children)
        return f"{wrap}{inner}{wrap}" if inner.strip() else inner
    if node.tag == "code":
        return f"`{''.join(_render_inline(c, images) for c in node.children)}`"
    if node.tag == "a":
        href = node.attrs.get("href", "")
        inner = "".join(_render_inline(c, images) for c in node.children)
        destination = _md_link_destination(href) if href else None
        return f"[{inner}]({destination})" if destination else inner
    if node.tag == "br":
        return "  \n"
    if node.tag == "img":
        src = node.attrs.get("src", "")
        alt = node.attrs.get("alt", "")
        path = images.add(src)
        return f"![{alt}]({path})" if path else ""
    return "".join(_render_inline(c, images) for c in node.children)


def _inline_text(node: _Node, images: ImageCollector) -> str:
    return "".join(_render_inline(c, images) for c in node.children)


def _render_list(node: _Node, images: ImageCollector, ordered: bool, depth: int) -> list[str]:
    lines = []
    index = 1
    indent = "  " * depth
    for li in node.children:
        if li.tag != "li":
            continue
        marker = f"{index}." if ordered else "-"
        index += 1
        text_parts = []
        sub_lines = []
        for child in li.children:
            if child.tag == "p":
                text_parts.append(_inline_text(child, images))
            elif child.tag in ("ul", "ol"):
                sub_lines.extend(_render_list(child, images, child.tag == "ol", depth + 1))
            elif child.text and child.text.strip():
                text_parts.append(_escape_html_breakout(child.text.strip()))
            else:
                text_parts.append(_render_inline(child, images))
        lines.append(f"{indent}{marker} " + " ".join(p for p in text_parts if p.strip()))
        lines.extend(sub_lines)
    return lines


def _escape_pipe(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _cell_text(node: _Node, images: ImageCollector) -> str:
    parts = []
    for child in node.children:
        if child.tag == "p":
            parts.append(_inline_text(child, images))
        elif child.text is not None:
            if child.text.strip():
                parts.append(_escape_html_breakout(child.text.strip()))
        else:
            parts.append(_inline_text(child, images))
    return _escape_pipe(" ".join(p for p in parts if p))


def _find_rows(node: _Node) -> list[_Node]:
    rows = [c for c in node.children if c.tag == "tr"]
    if rows:
        return rows
    for child in node.children:
        if child.tag in ("thead", "tbody", "tfoot"):
            rows.extend(c for c in child.children if c.tag == "tr")
    return rows


def _int_attr(node: _Node, name: str, default: int = 1) -> int:
    try:
        value = int(node.attrs.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _table_grid(rows: list[_Node], images: ImageCollector) -> list[list[str]]:
    # GFM tables have no notion of colspan/rowspan, so a merged cell is
    # spelled out once at its origin and left blank in every column/row it
    # otherwise covers — that keeps every row the same width (required for
    # a valid MD table) without inventing content the report didn't have.
    grid: list[list[str]] = []
    occupied: dict[tuple[int, int], bool] = {}
    for row_index, row in enumerate(rows):
        cells = [c for c in row.children if c.tag in ("th", "td")]
        line: list[str] = []
        col = 0
        for cell in cells:
            while occupied.get((row_index, col)):
                line.append("")
                col += 1
            colspan = _int_attr(cell, "colspan")
            rowspan = _int_attr(cell, "rowspan")
            line.append(_cell_text(cell, images))
            for i in range(1, colspan):
                line.append("")
            for r in range(1, rowspan):
                for c in range(colspan):
                    occupied[(row_index + r, col + c)] = True
            col += colspan
        while occupied.get((row_index, col)):
            line.append("")
            col += 1
        grid.append(line)
    width = max((len(line) for line in grid), default=0)
    for line in grid:
        line.extend([""] * (width - len(line)))
    return grid


def _render_table_from_html(node: _Node, images: ImageCollector) -> list[str]:
    rows = _find_rows(node)
    if not rows:
        return []
    grid = _table_grid(rows, images)
    if not grid or not grid[0]:
        return []
    header_cells, *body_rows = grid
    lines = ["| " + " | ".join(header_cells) + " |", "| " + " | ".join("---" for _ in header_cells) + " |"]
    for cells in body_rows:
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _text_content(node: _Node) -> str:
    if node.text is not None:
        return node.text
    return "".join(_text_content(c) for c in node.children)


def _render_block_node(node: _Node, images: ImageCollector) -> list[str]:
    if node.tag == "p":
        text = _inline_text(node, images)
        if not text.strip():
            return []
        # Markdown has no font-size notion — "lead" (see tiptap_render.py)
        # is a paragraph, not a heading, so bold is the closest equivalent
        # emphasis without implying a heading a Markdown reader would treat
        # as a structural/TOC-worthy entry.
        if "report-lead" in (node.attrs.get("class") or "").split():
            text = f"**{text}**"
        return [text, ""]
    if node.tag and re.fullmatch(r"h[1-6]", node.tag):
        level = int(node.tag[1])
        return ["#" * level + " " + _inline_text(node, images), ""]
    if node.tag == "ul":
        return _render_list(node, images, ordered=False, depth=0) + [""]
    if node.tag == "ol":
        return _render_list(node, images, ordered=True, depth=0) + [""]
    if node.tag == "blockquote":
        inner: list[str] = []
        for child in node.children:
            inner.extend(_render_block_node(child, images))
        return [("> " + line if line else ">") for line in inner] + [""]
    if node.tag == "pre":
        code_node = next((c for c in node.children if c.tag == "code"), node)
        return ["```", _text_content(code_node), "```", ""]
    if node.tag == "hr":
        return ["---", ""]
    if node.tag == "table":
        return _render_table_from_html(node, images) + [""]
    if node.tag == "img":
        rendered = _render_inline(node, images)
        return [rendered, ""] if rendered else []
    if node.tag in (None,) and node.text is not None:
        return [_escape_html_breakout(node.text.strip())] if node.text.strip() else []
    lines = []
    for child in node.children:
        lines.extend(_render_block_node(child, images))
    return lines


def html_to_markdown(html: str, images: ImageCollector) -> str:
    if not html:
        return ""
    builder = _TreeBuilder()
    builder.feed(html)
    lines = _render_block_node(builder.root, images)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _render_table_md(block: TableBlock) -> str:
    def esc(cell) -> str:
        text = cell.text if isinstance(cell, StyledText) else str(cell)
        return _escape_html_breakout(text).replace("|", "\\|").replace("\n", " ")

    lines = []
    if block.columns:
        lines.append("| " + " | ".join(esc(c) for c in block.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in block.columns) + " |")
    for row in block.rows:
        lines.append("| " + " | ".join(esc(cell) for cell in row) + " |")
    return "\n".join(lines)


def _render_cover_markdown(meta) -> str:
    lines = []
    if meta.cover_title:
        lines.append(f"### {_escape_html_breakout(meta.cover_title)}")
        lines.append("")
    lines.append(f"# {_escape_html_breakout(meta.client_name)}")
    lines.append("")
    lines.append(f"**{_escape_html_breakout(meta.classification_label)}**  ")
    line = f"Project {_escape_html_breakout(meta.project_id)}"
    if meta.test_type_label:
        line += f" &middot; {_escape_html_breakout(meta.test_type_label)}"
    lines.append(line + "  ")
    lines.append(meta.report_date)
    if meta.is_remediation_report:
        lines.append("")
        lines.append("_Remediation Report_")
    return "\n".join(lines)


def _render_toc_markdown(document: ReportDocument) -> str:
    lines = [f"## {_escape_html_breakout(document.meta.toc_heading)}", ""]

    def toc_entry(s: Section, depth: int):
        heading_text = _heading_text(s)
        slug = _md_slug(heading_text)
        indent = "  " * (depth - 1)
        lines.append(f"{indent}- [{heading_text}](#{slug})")
        walk(s.children, depth + 1)

    def walk(sections, depth):
        for s in sections:
            if s.toc_entry:
                toc_entry(s, depth)
            else:
                # Not a TOC entry itself (an anonymous template wrapper, a
                # finding subsection, ...) but a descendant still might be
                # — see ir_render._toc_entries_html for the same reasoning.
                walk(s.children, depth)

    walk(document.sections, 1)
    return "\n".join(lines)


def _render_block(block, images: ImageCollector, document: ReportDocument) -> str:
    if isinstance(block, RichTextBlock):
        return html_to_markdown(block.html, images)
    if isinstance(block, TableBlock):
        return _render_table_md(block)
    if isinstance(block, ListBlock):
        marker = "1." if block.ordered else "-"
        return "\n".join(f"{marker} {_escape_html_breakout(item)}" for item in block.items)
    if isinstance(block, CodeBlock):
        return f"```{block.language}\n{block.text}\n```"
    if isinstance(block, ImageBlock):
        path = images.add(block.src)
        return f"![{block.alt}]({path})" if path else ""
    if isinstance(block, BarGraphBlock):
        return _render_table_md(block.fallback)
    if isinstance(block, CoverPageBlock):
        return _render_cover_markdown(document.meta)
    if isinstance(block, TableOfContentsBlock):
        return _render_toc_markdown(document)
    return ""


def _md_slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def _heading_text(section: Section) -> str:
    title = _escape_html_breakout(section.title) if section.title else section.title
    return f"{section.number} {title}" if section.number else title


def render_document_markdown(document: ReportDocument) -> tuple[str, dict[str, bytes]]:
    images = ImageCollector()
    parts: list[str] = []

    def walk(section: Section, depth: int):
        heading_text = _heading_text(section)
        if section.title:
            parts.append("#" * min(depth, 6) + " " + heading_text)
            parts.append("")
        for block in section.blocks:
            rendered = _render_block(block, images, document)
            if rendered:
                parts.append(rendered)
                parts.append("")
        for child in section.children:
            walk(child, depth + 1)

    for top in document.sections:
        walk(top, 1)

    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, images.files
