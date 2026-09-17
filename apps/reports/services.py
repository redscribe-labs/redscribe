import base64
import re
from dataclasses import dataclass, field
from uuid import UUID

from cryptography.exceptions import InvalidTag

from apps.crypto.models import EncryptedBlob
from apps.crypto.services import decrypt_bytes, record_aad
from apps.findings.models import ContentSectionDefinition, Finding

from .tiptap_render import tiptap_to_html

PUBLISHABLE_STATUSES = {Finding.WorkflowStatus.QA_APPROVED}

_BLOB_URL_RE = re.compile(
    r"/engagements/(?P<engagement_id>[0-9a-fA-F-]{36})/blobs/(?P<blob_id>[0-9a-fA-F-]{36})/?$"
)


@dataclass
class RenderedFinding:
    finding: Finding
    section_html: dict = field(default_factory=dict)
    section_json: dict = field(default_factory=dict)
    affects_list: list = field(default_factory=list)
    classification_names: list = field(default_factory=list)
    retest_records: list = field(default_factory=list)


def _resolve_blob_bytes(engagement, project_key, src, cache: dict):
    """Shared primitive behind both image resolvers below — decrypts an
    EncryptedBlob referenced by a finding's image src exactly once per blob
    (cached), regardless of which resolver variant asks for it."""
    if not src:
        return None
    match = _BLOB_URL_RE.search(src)
    if not match:
        return None
    if UUID(match.group("engagement_id")) != engagement.pk:
        return None
    blob_id = match.group("blob_id")
    if blob_id in cache:
        return cache[blob_id]
    try:
        blob = EncryptedBlob.objects.get(pk=blob_id, engagement=engagement)
        plaintext = decrypt_bytes(
            bytes(blob.ciphertext), project_key,
            associated_data=record_aad("encryptedblob", blob.id, "ciphertext"),
        )
    except (EncryptedBlob.DoesNotExist, ValueError, InvalidTag):
        cache[blob_id] = None
        return None
    result = (plaintext, blob.content_type)
    cache[blob_id] = result
    return result


def _make_image_resolver(engagement, project_key):
    """HTML/PDF/Markdown resolver — returns a data: URI string."""
    cache: dict = {}

    def resolve(src):
        resolved = _resolve_blob_bytes(engagement, project_key, src, cache)
        if resolved is None:
            return None
        plaintext, content_type = resolved
        return f"data:{content_type};base64,{base64.b64encode(plaintext).decode('ascii')}"

    return resolve


def make_docx_image_resolver(engagement, project_key):
    """DOCX resolver — returns raw (bytes, content_type) for run.add_picture(),
    which has no notion of a data: URI."""
    cache: dict = {}

    def resolve(src):
        return _resolve_blob_bytes(engagement, project_key, src, cache)

    return resolve


def _decrypt_rich_text(ciphertext, project_key, associated_data: bytes = b"") -> str:
    if not ciphertext:
        return ""
    try:
        return decrypt_bytes(bytes(ciphertext), project_key, associated_data=associated_data).decode("utf-8")
    except (ValueError, InvalidTag):
        return ""


def _decrypt_finding_sections(finding: Finding, project_key, sections) -> dict[str, str]:
    """Raw decrypted TipTap JSON per active ContentSectionDefinition slug —
    shared by the HTML-flattening path below (_render_finding) and the DOCX
    path (apps.reports.docx_export), which needs the structured JSON rather
    than pre-flattened HTML to build a styled subdocument."""
    existing_sections = {fs.definition_id: fs for fs in finding.sections.all()}
    section_json = {}
    for definition in sections:
        finding_section = existing_sections.get(definition.id)
        content = _decrypt_rich_text(
            finding_section.content_ciphertext if finding_section else None, project_key,
            associated_data=record_aad("finding", finding.pk, definition.slug),
        )
        if content:
            section_json[definition.slug] = content
    return section_json


def _decrypt_retest_notes(finding: Finding, project_key) -> list[dict]:
    """Raw decrypted retest-record fields (notes as TipTap JSON) — shared the
    same way as _decrypt_finding_sections above."""
    return [
        {
            "date": record.created_at.strftime("%Y-%m-%d"),
            "tested_by": str(record.tested_by) if record.tested_by else "—",
            "status_display": record.get_status_display(),
            "notes_json": _decrypt_rich_text(
                record.notes_ciphertext, project_key,
                associated_data=record_aad("retestrecord", record.pk, "notes"),
            ),
        }
        for record in finding.retest_records.select_related("tested_by").order_by("created_at")
    ]


def _render_finding(finding: Finding, project_key, image_resolver, sections=None, text_transform=None) -> RenderedFinding:
    sections = list(ContentSectionDefinition.objects.filter(is_active=True)) if sections is None else sections
    section_json = _decrypt_finding_sections(finding, project_key, sections)
    section_html = {
        slug: tiptap_to_html(content, image_resolver=image_resolver, text_transform=text_transform)
        for slug, content in section_json.items()
    }

    retest_records = [
        {
            **record,
            "notes_html": tiptap_to_html(
                record["notes_json"], image_resolver=image_resolver, text_transform=text_transform,
            ),
        }
        for record in _decrypt_retest_notes(finding, project_key)
    ]

    return RenderedFinding(
        finding=finding,
        section_html=section_html,
        section_json=section_json,
        affects_list=finding.affects_list,
        classification_names=[str(tag) for tag in finding.classifications.all()],
        retest_records=retest_records,
    )


