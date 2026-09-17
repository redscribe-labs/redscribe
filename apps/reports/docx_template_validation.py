import io
import zipfile

import docx.opc.exceptions
from docx import Document
from docxtpl import DocxTemplate
from jinja2.exceptions import TemplateError

from . import docx_export


class DocxTemplateValidationError(Exception):
    """Raised when an uploaded .docx isn't usable as a Report Profile
    template — either it isn't a real Word document, or docxtpl can't
    render it against a realistic (dummy) context. Surfaced as a form
    error at upload time, not left to fail at export time against a real
    engagement."""


def validate_docx_template(data: bytes) -> None:
    """Real-format check, mirroring branding_views._detect_image_content_type's
    "verify with the real library, not the browser content-type" approach."""
    try:
        Document(io.BytesIO(data))
    except (docx.opc.exceptions.PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise DocxTemplateValidationError("That file isn't a valid Word (.docx) document.") from exc


def dry_run_render(profile) -> None:
    """Renders the just-uploaded template against a cheap dummy context —
    catches a malformed {%p for %}/{%tr for %} loop or an unknown tag at
    upload time, not at export time against a real engagement's data."""
    try:
        tpl, context = docx_export.build_dummy_context(profile)
        tpl.render(context)
    except TemplateError as exc:
        raise DocxTemplateValidationError(
            f"This template couldn't be rendered — check its {{{{ tags }}}} and any "
            f"{{%p for %}}/{{%tr for %}} loop syntax against the placeholder reference below: {exc}"
        ) from exc
    except Exception as exc:
        raise DocxTemplateValidationError(f"This template couldn't be rendered: {exc}") from exc
