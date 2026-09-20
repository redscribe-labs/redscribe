import html as _html

from . import ir_render
from .report_ir import ReportDocument

_STANDALONE_CSS = """
body { margin: 0; background: #f1f5f9; }
.report-document { max-width: 56rem; margin: 2rem auto; padding: 2.5rem; background: #fff;
  border-radius: .5rem; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
"""


def build_html(document: ReportDocument) -> bytes:
    meta = document.meta
    title = f"{meta.client_name} — {meta.test_type_label}" if meta.test_type_label else meta.client_name

    html_doc = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_html.escape(title, quote=True)}</title>"
        f"<style>{ir_render.build_preview_css(meta)}{_STANDALONE_CSS}</style>"
        "</head><body>"
        f"{ir_render.render_document_html(document)}"
        "</body></html>"
    )
    return html_doc.encode("utf-8")
