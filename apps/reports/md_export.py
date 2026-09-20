import io
import zipfile

from .markdown_render import render_document_markdown
from .report_ir import ReportDocument


def build_markdown_zip(document: ReportDocument) -> bytes:
    markdown_text, images = render_document_markdown(document)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.md", markdown_text)
        for filename, content in images.items():
            zf.writestr(f"images/{filename}", content)
    return buffer.getvalue()
