import html

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

_MAX_HEADING_LEVEL = 6

_PREVIEW_CSS_BASE = """
.report-document {{ font-family: "{body_font}", sans-serif; font-size: .8rem; line-height: 1.6; color: #1e293b; }}
/* Only weights 400/700 are ever fetched for a custom Google Font (see
   google_fonts.py) — anything in between falls back to synthesized/faux
   bold rather than a real face, so hierarchy below is built from size,
   color and letter-spacing, never an in-between weight.
   Deliberately no border/rule under ANY heading level any more (h2 used
   to carry one): it read fine for a rare true section break, but the
   same h2 also lands under every short/empty subsection and every
   fixed-depth subsection a template produces, where a full-width line
   under one sentence — or nothing at all — reads as clutter rather than
   structure. Hierarchy now comes from size + color + spacing alone. */
.report-document h1 {{ font-size: 1.55rem; margin: 0 0 1rem; font-weight: 700; line-height: 1.25; color: #0f172a; }}
.report-document h2 {{ font-size: 1.1rem; margin: 1.9rem 0 .65rem; font-weight: 700; line-height: 1.3; color: #0f172a; }}
/* Themed rather than plain black — this is the level a repeated "entry"
   title lands on (each finding, each observation, each testing phase),
   so tying it to the profile's own accent color reads as a deliberate
   design choice rather than yet another black heading in a long list of
   them. */
.report-document h3 {{ font-size: 1rem; margin: 1.5rem 0 .55rem; font-weight: 700; line-height: 1.3; color: {theme_color}; }}
/* The deepest, most repeated level (per-finding field labels like
   "Vulnerability description", "Business impact") — styled as compact
   uppercase eyebrow labels instead of full headings, so a finding-dense
   report doesn't read as a wall of same-weight bold text. */
.report-document h4, .report-document h5, .report-document h6 {{
    font-size: .68rem; margin: 1.15rem 0 .4rem; font-weight: 700; line-height: 1.3;
    text-transform: uppercase; letter-spacing: .06em; color: #64748b;
}}
.report-document strong {{ font-weight: 700; }}
.report-document p {{ margin: 0 0 .65rem; }}
/* "Lead" text (tiptap_render.py's paragraph "lead" attr) — a purely
   visual size bump for a paragraph that should read as emphasized intro
   copy, with none of a real heading's structure: no numbering, no TOC
   entry, no section nesting (it's still just a <p> to everything in
   assembly.py). Body color, not the h3 accent color, so it's never
   mistaken for an actual entry title. */
.report-lead {{ font-size: 1.05rem; font-weight: 700; line-height: 1.35; margin: .9rem 0 .5rem; color: inherit; }}
/* The whole first page — cover meta block, and disclaimers (if any) right
   below it — vertically AND horizontally centered as one group. In the
   PDF this fills the actual @page front content box (pdf_export.py sets
   its min-height there); in the live preview it just centers within
   whatever height the pane happens to have, which is close enough for
   "does this read as a real cover page" purposes. */
.report-cover-page {{ display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 2rem 1rem; }}
.report-cover-logo {{ max-height: 3.5rem; max-width: 60%; margin: 0 auto .75rem; display: block; }}
.report-cover-firm {{ color: #475569; font-size: .8rem; font-weight: 600; margin-bottom: .5rem; }}
.report-classification {{ font-size: .7rem; letter-spacing: .05em; text-transform: uppercase; color: #b91c1c; font-weight: 600; }}
.report-cover-title {{ color: #475569; font-size: 1rem; font-weight: 600; margin: 1rem 0 .25rem; }}
.report-cover-meta, .report-cover-date {{ color: #64748b; font-size: .8rem; }}
.report-cover-flag {{ color: #b45309; font-weight: 600; font-size: .75rem; margin-top: .5rem; }}
.report-cover-page .report-section {{ text-align: left; margin-top: 2rem; max-width: 32rem; }}
/* Horizontal row separators only — no vertical cell borders and no
   border-collapse at all. A full grid (border on all four sides of every
   cell, collapsed) read as a harsh, spreadsheet-y "Table" rather than
   blending into the report; it was ALSO the source of a WeasyPrint
   rendering bug where collapse could leave a hairline page-background gap
   between adjacent rows whose cells carry their own background color (a
   colored Severity/Status cell). One border per row boundary (drawn by
   that row's own border-bottom, never doubled with the next row's
   border-top) avoids both problems at once. */
.report-table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin: .85rem 0 1.4rem; font-size: .78rem; }}
.report-table th, .report-table td {{ border: none; border-bottom: 1px solid #e2e8f0; padding: .55rem .65rem; text-align: left; }}
.report-table tbody tr:last-child td {{ border-bottom: none; }}
.report-table th {{ background: {table_header_color}; color: {table_header_text_color}; border-bottom-color: {table_header_color}; }}
/* Any cell without its own explicit color (a Severity/Status badge sets
   one inline, which always wins over this) falls back to the profile's
   configured empty-cell fill instead of the page's plain white. */
.report-table td {{ background: {empty_cell_background_color}; }}
.report-table td p, .report-table th p {{ margin: 0; }}
/* Vertical bars, spread across the FULL width (flex:1 per column, not a
   fixed width) so the chart doesn't look cramped to one side — and one
   column per severity ALWAYS, even a severity with zero findings either
   way (see apps.reports.assembly._breakdown_section), so the full
   severity spectrum is visible at a glance rather than only whichever
   levels happened to have findings. Chart only; no companion table in
   HTML/PDF (the table fallback is still used, unchanged, for the
   Markdown export, which has no chart capability of its own — see
   report_ir.BarGraphBlock). */
.report-bargraph-vertical {{ display: flex; align-items: flex-end; gap: .9rem; margin: .75rem 0 1.25rem; width: 100%; }}
/* NOT display:flex — see .report-vbar-track's comment below for the
   general shape of the bug this avoids. Here it showed up on WIDTH: a
   column that's a flex item of the row above AND its own flex container
   (column direction, for centering value/track/label) made WeasyPrint
   size every column to the FULL row width instead of dividing it among
   siblings — bars ended up stacked on top of each other rather than
   spread evenly across the chart. Plain block flow doesn't need flex here
   at all: value/track/label are already block-level (stack vertically on
   their own) and text-align centers the text ones; the track fills the
   column's width just by being a block. flex:1 1 0 (a normal, single-role
   flex-item property) is what actually makes columns share the row
   equally and therefore span the full chart width regardless of how many
   severities have a bar. */
.report-vbar-col {{ flex: 1 1 0; min-width: 0; text-align: center; }}
.report-vbar-value {{ font-size: .7rem; font-weight: 600; color: #1e293b; margin-bottom: .2rem; }}
/* Two WeasyPrint-specific bugs, both worked around here (Chrome/the live
   preview render the "obvious" version — flex track, span tags — with no
   issue at all, so this is PDF-only). Both are really the same root cause
   (see .report-vbar-col's own comment above): an element that is BOTH a
   flex item along one axis AND its own flex container along the other
   gets its own size along the OUTER axis miscomputed by WeasyPrint.
   1. When the track itself was display:flex (row, for align-items:
      flex-end) as well as a flex item of .report-vbar-col (column), its
      own laid-out HEIGHT collapsed to roughly its max-width value instead
      of the specified height — every severity's track ended up the same
      ~2.8rem-tall box regardless of the real 17rem, clipping the
      (correctly-computed) percentage fill into a near-invisible sliver
      for every bar. Fixed by dropping display:flex from the track
      entirely — bottom-aligning the fill needs position:absolute now
      instead.
   2. With the track no longer a flex container, if track/fill were
      <span> (inline-origin) elements, WeasyPrint would resolve the
      absolutely-positioned fill's percentage height against the
      surrounding anonymous line box (~1 line tall) instead of the
      track's own containing block. <div>s (block-level from the start,
      see _render_bargraph) don't hit this. */
.report-vbar-track {{ position: relative; width: 100%; height: 17rem; background: #f1f5f9; border-radius: .2rem; overflow: hidden; }}
.report-vbar-fill {{ position: absolute; bottom: 0; left: 0; width: 100%; }}
.report-vbar-label {{ font-size: .65rem; color: #64748b; text-align: center; line-height: 1.2; margin-top: .3rem; }}
/* Light tint of the same table-theme color as everything else themed
   below (not an independent palette choice) — darker border/text for
   contrast against it. Long unbroken lines wrap instead of running off
   the printed page (WeasyPrint has no horizontal scroll to fall back on
   the way a browser tab does). */
.report-section pre, .report-section pre code {{ font-family: "{monospace_font}", monospace; }}
.report-section pre {{
    background: {code_bg}; color: {code_text}; border: 1px solid {code_border}; border-radius: .4rem;
    padding: .6rem .75rem; font-size: .75rem;
    white-space: pre-wrap; overflow-wrap: anywhere;
}}
/* Highlight and links both key off the same table-theme color as the
   code block and table headers above — one consistent report accent
   color throughout, rather than an independent yellow/blue. */
.report-document mark {{ background: {theme_color}; color: {theme_text}; padding: .15em .3em; margin: 0 .05em; border-radius: .15em; box-decoration-break: clone; -webkit-box-decoration-break: clone; }}
.report-document a {{ color: {theme_color}; text-decoration: underline; }}
/* Same border color as the code block above (code_border, itself a
   darker tint of the table-theme color) — one consistent "framed content"
   look, rather than screenshots floating with no visual boundary. Full
   width (not just max-width) so a screenshot reads at a legible size in
   the printed page rather than sitting small — per report_ir.ImageBlock,
   these are pentest screenshots, always uploaded well above print
   resolution, so stretching to the column width doesn't blur them. */
.report-document figure {{ background: transparent; border: 1px solid {code_border}; border-radius: .4rem; padding: .4rem; margin: .5rem 0; width: 100%; box-sizing: border-box; }}
.report-document figure img {{ display: block; width: 100%; max-width: 100%; background: transparent; }}
.report-document figcaption {{ font-size: .7rem; color: #64748b; margin-top: .35rem; }}
.report-document ul {{ list-style: none; padding-left: 1.2rem; margin: 0 0 .65rem; }}
.report-document ul > li {{ position: relative; margin-bottom: .35rem; }}
.report-document ul > li:last-child {{ margin-bottom: 0; }}
.report-document ul > li::before {{ content: "{bullet}"; position: absolute; left: -1.1rem; }}
.report-toc {{ font-size: 1rem; }}
.report-toc h2 {{ font-size: 1.4rem; margin-top: 0; }}
.report-toc ul {{ list-style: none; padding: 0; margin: 0; }}
.report-toc ul ul {{ padding-left: 1.1rem; margin-top: .3rem; }}
.report-toc ul > li::before {{ content: none; }}
.report-toc li {{ margin: .45rem 0; }}
.report-toc ul ul li {{ font-size: .9rem; margin: .3rem 0; }}
.report-toc a {{ color: {theme_color}; text-decoration: none; }}
"""


def _css_string_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace('"', '\\"')
        .replace("<", "\\3C ").replace(">", "\\3E ")
    )


def _font_face_css(family: str) -> str:
    import base64

    from .models import CachedGoogleFont

    variants = CachedGoogleFont.objects.filter(family=family)
    if not variants:
        return ""
    rules = []
    for variant in variants:
        data_uri = f"data:{variant.content_type};base64,{base64.b64encode(bytes(variant.font_data)).decode('ascii')}"
        rules.append(
            "@font-face {{ font-family: \"{family}\"; font-weight: {weight}; font-style: {style}; "
            "src: url({data_uri}) format(\"{fmt}\"); font-display: swap; }}".format(
                family=_css_string_escape(family), weight=variant.weight, style=variant.style,
                data_uri=data_uri, fmt=variant.font_format,
            )
        )
    return "".join(rules)


def build_preview_css(meta=None) -> str:
    from .colors import contrasting_text_rgb, darken, mix_with_white

    body_font = (meta and meta.body_font) or "Helvetica"
    monospace_font = (meta and meta.monospace_font) or "Courier New"
    font_faces = _font_face_css(body_font) + (_font_face_css(monospace_font) if monospace_font != body_font else "")
    table_header_color = (meta and meta.table_header_color) or "rgba(248,250,252,1)"
    empty_cell_background_color = (meta and meta.empty_cell_background_color) or "transparent"
    text_rgb = contrasting_text_rgb(table_header_color)
    theme_text_rgb = contrasting_text_rgb(table_header_color)
    code_bg = mix_with_white(table_header_color, 0.85)
    code_border = darken(table_header_color, 0.15)
    return font_faces + _PREVIEW_CSS_BASE.format(
        body_font=_css_string_escape(body_font),
        monospace_font=_css_string_escape(monospace_font),
        bullet=_css_string_escape((meta and meta.bullet_character) or "•"),
        table_header_color=_css_string_escape(table_header_color),
        table_header_text_color=f"rgb({text_rgb[0]},{text_rgb[1]},{text_rgb[2]})",
        empty_cell_background_color=_css_string_escape(empty_cell_background_color),
        code_bg=_css_string_escape(code_bg),
        code_border=_css_string_escape(code_border),
        code_text="#1e293b",
        theme_color=_css_string_escape(table_header_color),
        theme_text=f"rgb({theme_text_rgb[0]},{theme_text_rgb[1]},{theme_text_rgb[2]})",
    )


def _escape(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _render_cell(cell) -> str:
    if isinstance(cell, StyledText):
        if cell.background_rgba:
            from .colors import contrasting_text_rgb

            r, g, b = contrasting_text_rgb(cell.background_rgba)
            style = f"background:{_escape(cell.background_rgba)};color:rgb({r},{g},{b})"
            return f'<td style="{style}"><strong>{_escape(cell.text)}</strong></td>'
        return f"<td>{_escape(cell.text)}</td>"
    return f"<td>{_escape(cell)}</td>"


def _render_table(block: TableBlock) -> str:
    head = "".join(f"<th>{_escape(c)}</th>" for c in block.columns)
    body_rows = []
    for row in block.rows:
        if block.header_column and row:
            first_cell = f"<th>{_escape(row[0].text if isinstance(row[0], StyledText) else row[0])}</th>"
            cells = first_cell + "".join(_render_cell(cell) for cell in row[1:])
        else:
            cells = "".join(_render_cell(cell) for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    thead = f"<thead><tr>{head}</tr></thead>" if any(block.columns) else ""
    return f'<table class="report-table">{thead}<tbody>{"".join(body_rows)}</tbody></table>'


def _render_list(block: ListBlock) -> str:
    tag = "ol" if block.ordered else "ul"
    items = "".join(f"<li>{_escape(item)}</li>" for item in block.items)
    return f"<{tag}>{items}</{tag}>"


def _render_bargraph(block: BarGraphBlock) -> str:
    max_value = max((bar.value for bar in block.series), default=0) or 1
    cols = []
    for bar in block.series:
        pct = round(bar.value / max_value * 100, 1)
        cols.append(
            f'<div class="report-vbar-col">'
            f'<div class="report-vbar-value">{bar.value}</div>'
            f'<div class="report-vbar-track"><div class="report-vbar-fill" '
            f'style="height:{pct}%;background:{_escape(bar.color_rgba)}"></div></div>'
            f'<div class="report-vbar-label">{_escape(bar.label)}</div>'
            f"</div>"
        )
    return f'<div class="report-bargraph-vertical" role="img" aria-label="Findings by severity">{"".join(cols)}</div>'


def _render_code(block: CodeBlock) -> str:
    lang_attr = f' data-language="{_escape(block.language)}"' if block.language else ""
    return f"<pre{lang_attr}><code>{_escape(block.text)}</code></pre>"


def _render_image(block: ImageBlock) -> str:
    caption = f"<figcaption>{_escape(block.caption)}</figcaption>" if block.caption else ""
    return f'<figure><img src="{_escape(block.src)}" alt="{_escape(block.alt)}">{caption}</figure>'


def _toc_entries_html(sections: list) -> str:
    parts = []
    for section in sections:
        sub_entries = _toc_entries_html(section.children)
        if section.toc_entry:
            link = f'<a href="#sec-{_escape(section.key)}">{_escape(section.number)} {_escape(section.title)}</a>'
            sub_list = f"<ul>{sub_entries}</ul>" if sub_entries else ""
            parts.append(f"<li>{link}{sub_list}</li>")
        elif sub_entries:
            # This section itself isn't a TOC entry (a template's own
            # implicit wrapper around content with no heading above it, a
            # finding subsection, ...) but something nested under it is —
            # e.g. a profile with no typed headings at all still gets a
            # working TOC out of the finding/observation/phase titles
            # underneath, rather than losing them because their immediate
            # parent never wanted a link of its own.
            parts.append(sub_entries)
    return "".join(parts)


def render_toc(document: ReportDocument) -> str:
    entries = _toc_entries_html(document.sections)
    heading = _escape(document.meta.toc_heading)
    return f'<nav class="report-toc report-page-break"><h2>{heading}</h2><ul>{entries}</ul></nav>'


def render_cover_html(meta) -> str:
    branding_html = ""
    if meta.firm_logo_data_uri:
        branding_html = f'<img class="report-cover-logo" src="{_escape(meta.firm_logo_data_uri)}" alt="{_escape(meta.firm_name)}">'
    elif meta.firm_name:
        branding_html = f'<p class="report-cover-firm">{_escape(meta.firm_name)}</p>'

    cover_block = (
        branding_html
        + f'<div class="report-classification">{_escape(meta.classification_label)}</div>'
        + (f'<p class="report-cover-title">{_escape(meta.cover_title)}</p>' if meta.cover_title else "")
        + f'<h1>{_escape(meta.client_name)}</h1>'
        f'<p class="report-cover-meta">Project {_escape(meta.project_id)}'
        + (f" &middot; {_escape(meta.test_type_label)}" if meta.test_type_label else "")
        + f'</p><p class="report-cover-date">{_escape(meta.report_date)}</p>'
        + ('<p class="report-cover-flag">Remediation Report</p>' if meta.is_remediation_report else "")
    )
    # pdf-front switches this subtree to the cover's own @page context (no
    # header/footer/page-number, its own margins) — see pdf_export.py. The
    # page-context change alone forces a break on entry and on exit, so
    # whatever follows resumes the ambient page context automatically,
    # wherever in the document this block actually sits.
    return f'<section class="report-cover-page pdf-front">{cover_block}</section>'


def _render_block(block, document: ReportDocument) -> str:
    if isinstance(block, RichTextBlock):
        return block.html
    if isinstance(block, TableBlock):
        return _render_table(block)
    if isinstance(block, ListBlock):
        return _render_list(block)
    if isinstance(block, BarGraphBlock):
        return _render_bargraph(block)
    if isinstance(block, CodeBlock):
        return _render_code(block)
    if isinstance(block, ImageBlock):
        return _render_image(block)
    if isinstance(block, CoverPageBlock):
        return render_cover_html(document.meta)
    if isinstance(block, TableOfContentsBlock):
        return render_toc(document)
    return ""


def _render_section(section: Section, depth: int, document: ReportDocument) -> str:
    level = min(depth, _MAX_HEADING_LEVEL)
    heading_text = f"{section.number} {section.title}" if section.number else section.title
    parts = [f"<h{level}>{_escape(heading_text)}</h{level}>"] if section.title else []
    parts += [_render_block(b, document) for b in section.blocks]
    parts += [_render_section(child, depth + 1, document) for child in section.children]
    css_class = "report-section report-page-break" if section.page_break_before else "report-section"
    return f'<section class="{css_class}" id="sec-{_escape(section.key)}">{"".join(parts)}</section>'


def render_body_html(document: ReportDocument) -> str:
    return "".join(_render_section(s, 1, document) for s in document.sections)


def render_document_html(document: ReportDocument) -> str:
    return '<article class="report-document">' + render_body_html(document) + "</article>"
