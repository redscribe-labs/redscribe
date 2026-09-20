from . import ir_render
from .report_ir import ReportDocument

_PRINT_CSS_TEMPLATE = """
@page front {{
  size: A4;
  margin: 2.2cm;
}}
@page body {{
  /* Left/right corners, not one centered line — header text top-left,
     footer text bottom-left, page number bottom-right. Scoped to this
     @page (body) only, not @page front, so the cover page carries no
     page number at all — it's a different named page with no margin-box
     content of its own. */
  size: A4;
  margin: 2.6cm 2cm 2.8cm 2cm;
  @top-left {{ content: "{header_text}"; font-family: "{body_font}", sans-serif; font-size: 8pt; color: #64748b; }}
  @top-right {{ content: "{classification_text}"; font-family: "{body_font}", sans-serif; font-size: 8pt; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: #b91c1c; }}
  @bottom-left {{ content: "{footer_text}"; font-family: "{body_font}", sans-serif; font-size: 8pt; color: #64748b; }}
  @bottom-right {{ content: counter(page); font-family: "{body_font}", sans-serif; font-size: 8pt; color: #64748b; }}
}}
.pdf-front {{ page: front; }}
.pdf-body {{ page: body; break-before: page; }}
/* Deliberately NOT a blanket "every .report-section avoids breaking
   inside itself" rule anymore — that applied equally to a single small
   subsection AND to huge multi-child containers ("Vulnerability details"
   holding every finding, "Testing Methodology" holding its whole
   subtree, ...), and WeasyPrint's only way to honor "don't break inside"
   for a box too tall to fit the remaining page is to push the ENTIRE box
   onto a fresh page — which showed up as unwanted page breaks right
   after "Information gathering", right after the "Vulnerability
   details"/"Testing Methodology" headings, before individual findings'
   Technical details/Testing summary subsections, and before every
   Observation, none of which anyone asked to start a new page. Explicit
   page_break_before (see report_ir.Section) is now the only thing that
   forces a break.
   .report-table also used to be break-inside: avoid-page, on the theory
   that an individual table is always small/bounded — but every table this
   app actually renders (vulnerabilities summary, per-category checklist
   coverage, per-finding metadata, scan imports, retest history, document
   control) has a row count that scales with report data, so the same
   whole-box-relocation problem showed up again: a long table that didn't
   fit the remaining page got shoved in its entirety onto a fresh page,
   reading as a break right after the preceding heading. Tables should
   split BETWEEN rows instead; only a single row must never be split
   mid-row, and thead (present on every table except the finding metadata
   table's header-column-only layout) repeats on every page it spans. */
.report-table {{ break-inside: auto; }}
.report-table tr {{ break-inside: avoid; }}
.report-page-break {{ break-before: page; }}
/* WeasyPrint's own default stylesheet (not anything RedScribe sets) gives
   every heading break-after: avoid + break-inside: avoid, and every list
   break-before: avoid — both meant to stop a heading/list from being
   orphaned alone at the bottom of a page. For a report whose sections
   scale with data, this causes exactly the whole-box-relocation problem
   described above: when the content right after a heading (or a list)
   doesn't fit the remaining page, the renderer has no way to honor "don't
   break here" except by pushing the heading itself — and everything after
   it — onto a fresh page, which reads as an unexplained jump right at that
   heading. Per policy (breaks come only from an explicit
   page_break_before / Document Structure, plus the Table of Contents),
   headings and lists must not influence pagination on their own — this
   overrides WeasyPrint's default back to ordinary, unconstrained flow.
   The tradeoff is the one this ruled out on the other side: a heading can
   now end up alone at the bottom of a page with its content starting on
   the next one. */
h1, h2, h3, h4, h5, h6 {{ break-after: auto; break-inside: auto; }}
ol, ul {{ break-before: auto; }}
/* Fills the @page front content box (A4 25.7cm tall minus its own 2.2cm
   top+bottom margin) so .report-cover-page's title-block layout (see
   _PREVIEW_CSS_BASE) spans a full physical page — its content is anchored
   top/bottom within that height, not just packed to its own content's
   height. */
.report-cover-page {{ min-height: 25.3cm; }}
/* Word-style TOC line: title, a dotted leader filling the rest of the
   line, and the page number flush right — PDF-only, the live preview
   pane has no notion of a "page" at all so this is skipped there
   entirely. leader(".") is exactly what a real Word TOC does: it fills
   the remaining width of the line, in the SAME inline flow as the link's
   own title text, right up to whatever comes after it in the content
   list — no float/flex needed, that's the whole point of leader().
   target-counter() resolves each
   link's #sec-<key> fragment to whichever real page it ends up landing
   on, for both TOC nesting levels (same ".report-toc a" selector covers
   both level-1 and level-2 entries) — never needs to know any actual
   page number itself, just the id it already points at. */
.report-toc a {{ display: block; text-decoration: none; }}
.report-toc a::after {{
    content: leader(".") target-counter(attr(href), page);
    color: #94a3b8;
}}
"""


def _css_content_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace('"', '\\"')
        .replace("<", "\\3C ").replace(">", "\\3E ")
    )


def build_pdf(document: ReportDocument) -> bytes:
    from weasyprint import HTML

    meta = document.meta
    header_text = meta.client_name
    if meta.test_type_label:
        header_text += f" — {meta.test_type_label}"
    footer_text = f"{meta.firm_name} — {meta.project_id}" if meta.firm_name else meta.project_id

    print_css = _PRINT_CSS_TEMPLATE.format(
        header_text=_css_content_escape(header_text),
        footer_text=_css_content_escape(footer_text),
        classification_text=_css_content_escape(meta.classification_label),
        body_font=_css_content_escape(meta.body_font or "Plus Jakarta Sans"),
    )

    # Cover page and TOC now render inline wherever their tag sits in the
    # document (see ir_render.render_cover_html/render_toc) — .pdf-front's
    # page-context switch works no matter how deep it's nested, so no
    # separate top-level wrapper is needed for them any more.
    body_html = ir_render.render_body_html(document)

    html_doc = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{ir_render.build_preview_css(meta)}{print_css}</style>"
        "</head><body class=\"report-document\">"
        f'<div class="pdf-body">{body_html}</div>'
        + "</body></html>"
    )

    return HTML(string=html_doc).write_pdf()


def encrypt_pdf(pdf_bytes: bytes, password: str) -> bytes:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
