import html as _html

_ALLOWED_LINK_PROTOCOLS = ("http://", "https://", "mailto:")

_MAX_NODE_DEPTH = 60

_MARK_TAGS = {
    "bold": "strong",
    "italic": "em",
    "underline": "u",
    "strike": "s",
    "code": "code",
    "highlight": "mark",
}


def _escape(text) -> str:
    return _html.escape(str(text if text is not None else ""), quote=True)


def _render_marks(inner_html: str, marks: list) -> str:
    for mark in marks or []:
        mark_type = mark.get("type") if isinstance(mark, dict) else None
        if mark_type in _MARK_TAGS:
            tag = _MARK_TAGS[mark_type]
            inner_html = f"<{tag}>{inner_html}</{tag}>"
        elif mark_type == "link":
            href = ((mark.get("attrs") or {}).get("href") or "").strip()
            if href.lower().startswith(_ALLOWED_LINK_PROTOCOLS):
                inner_html = f'<a href="{_escape(href)}" rel="noopener noreferrer">{inner_html}</a>'
    return inner_html


def _span_attrs_html(attrs: dict) -> str:
    parts = []
    colspan = attrs.get("colspan")
    if isinstance(colspan, int) and colspan > 1:
        parts.append(f' colspan="{colspan}"')
    rowspan = attrs.get("rowspan")
    if isinstance(rowspan, int) and rowspan > 1:
        parts.append(f' rowspan="{rowspan}"')
    return "".join(parts)


def _table_colgroup_html(rows: list) -> str:
    # Reconstruct column widths set via the editor's column-resize handles.
    # Widths live on each tableCell/tableHeader's `colwidth` attr (one entry
    # per spanned column), so a colspan>1 cell can carry different widths
    # per column. rowspan cells occupy the same column index in later rows
    # without repeating their own colwidth, so we track which columns are
    # still "occupied" by an earlier row's rowspan to keep column indices
    # aligned across rows.
    widths: dict[int, int] = {}
    occupied: dict[int, int] = {}
    max_col = -1
    for row in rows:
        col = 0
        next_occupied: dict[int, int] = {}
        for cell in row.get("content") or []:
            if not isinstance(cell, dict):
                continue
            while occupied.get(col, 0) > 0:
                next_occupied[col] = occupied[col] - 1
                col += 1
            attrs = cell.get("attrs") or {}
            colspan = attrs.get("colspan") if isinstance(attrs.get("colspan"), int) else 1
            rowspan = attrs.get("rowspan") if isinstance(attrs.get("rowspan"), int) else 1
            colwidth = attrs.get("colwidth")
            for i in range(max(colspan, 1)):
                width = colwidth[i] if isinstance(colwidth, list) and i < len(colwidth) else None
                if isinstance(width, int) and width > 0 and col + i not in widths:
                    widths[col + i] = width
                if rowspan > 1:
                    next_occupied[col + i] = rowspan - 1
                max_col = max(max_col, col + i)
            col += max(colspan, 1)
        occupied = next_occupied
    if not widths:
        return ""
    cols_html = "".join(
        f'<col style="width: {widths[i]}px">' if i in widths else "<col>"
        for i in range(max_col + 1)
    )
    return f"<colgroup>{cols_html}</colgroup>"


def _render_node(node, image_resolver, text_transform, depth=0) -> str:
    if not isinstance(node, dict):
        return ""
    if depth > _MAX_NODE_DEPTH:
        return ""
    node_type = node.get("type")
    content = node.get("content") or []
    attrs = node.get("attrs") or {}

    if node_type == "text":
        text = node.get("text", "")
        if text_transform:
            text = text_transform(text)
        return _render_marks(_escape(text), node.get("marks"))

    children_html = "".join(
        _render_node(child, image_resolver, text_transform, depth + 1) for child in content
    )

    if node_type == "paragraph":
        # "Lead" is purely a visual size bump — a paragraph, not a heading
        # node, so it carries none of a heading's structural weight: no
        # numbering, no section nesting, and no table-of-contents entry
        # (see assembly._parse_template, which only ever looks at
        # node["type"] == "heading" to build sections at all).
        css_class = ' class="report-lead"' if attrs.get("lead") else ""
        return f"<p{css_class}>{children_html}</p>" if children_html else "<p><br></p>"
    if node_type == "heading":
        level = attrs.get("level")
        level = level if level in (1, 2, 3, 4, 5, 6) else 3
        return f"<h{level}>{children_html}</h{level}>"
    if node_type == "bulletList":
        return f"<ul>{children_html}</ul>"
    if node_type == "orderedList":
        return f"<ol>{children_html}</ol>"
    if node_type == "listItem":
        return f"<li>{children_html}</li>"
    if node_type == "blockquote":
        return f"<blockquote>{children_html}</blockquote>"
    if node_type == "codeBlock":
        return f"<pre><code>{children_html}</code></pre>"
    if node_type == "horizontalRule":
        return "<hr>"
    if node_type == "pageBreak":
        return '<div class="report-page-break"></div>'
    if node_type == "hardBreak":
        return "<br>"
    if node_type == "image":
        src = image_resolver(attrs.get("src")) if image_resolver else None
        if not src:
            return ""
        alt = _escape(attrs.get("alt") or "")
        return f'<img src="{_escape(src)}" alt="{alt}">'
    if node_type == "table":
        rows = [c for c in content if isinstance(c, dict) and c.get("type") == "tableRow"]
        has_real_header = any(
            isinstance(cell, dict) and cell.get("type") == "tableHeader"
            for row in rows for cell in (row.get("content") or [])
        )
        colgroup_html = _table_colgroup_html(rows)
        rows_html = []
        for i, row in enumerate(rows):
            force_header = not has_real_header and i == 0
            cells_html = []
            for cell in row.get("content") or []:
                if not isinstance(cell, dict):
                    continue
                cell_html = "".join(
                    _render_node(c, image_resolver, text_transform, depth + 1)
                    for c in (cell.get("content") or [])
                )
                cell_attrs = cell.get("attrs") or {}
                tag = "th" if (cell.get("type") == "tableHeader" or force_header) else "td"
                span_attrs = _span_attrs_html(cell_attrs)
                cells_html.append(f"<{tag}{span_attrs}>{cell_html}</{tag}>")
            rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
        table_style = ' style="table-layout: fixed"' if colgroup_html else ""
        return f'<table class="report-table"{table_style}>{colgroup_html}{"".join(rows_html)}</table>'
    if node_type == "tableRow":
        return f"<tr>{children_html}</tr>"
    if node_type == "tableHeader":
        return f"<th>{children_html}</th>"
    if node_type == "tableCell":
        return f"<td>{children_html}</td>"

    return children_html


def tiptap_to_html(doc_json: str, *, image_resolver=None, text_transform=None) -> str:
    import json

    if not doc_json:
        return ""
    try:
        parsed = json.loads(doc_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return _render_node(parsed, image_resolver, text_transform)
