import json
import os

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.crypto.services import decrypt_bytes, encrypt_bytes, generate_project_key, get_data_key, record_aad
from apps.engagements.models import Engagement, EngagementMembership

from . import recurrence, retest, review
from .models import (
    ClassificationTag, CommentEntry, CommentThread, ContentSectionDefinition, Finding, FindingSection,
    TemplateSection, VulnerabilityTemplate, VulnerabilityTemplateApprovedVersion,
)
from .permissions import can_edit_finding_content
from .validators import validate_cve_id, validate_cvss_vector, validate_tiptap_doc_json


def doc_json(text: str) -> str:
    return json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]})

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"

_CONTENT_FIELD_SLUGS = {
    "vulnerability_description": "vulnerability-description",
    "business_impact": "business-impact",
    "testing_summary": "testing-summary",
    "technical_details": "technical-details",
    "remediation_testing": "remediation-testing",
    "recommendations": "recommendations",
    "references": "references",
    "note": "note",
}


def section_post_key(name: str) -> str:
    return f"section__{_CONTENT_FIELD_SLUGS[name]}"


def seed_content_sections():
    flags = {
        "vulnerability-description": {},
        "business-impact": {},
        "testing-summary": {},
        "technical-details": {"supports_image_upload": True, "is_import_target": True},
        "remediation-testing": {
            "supports_image_upload": True, "portal_visible": True,
            "include_in_remediation_report_only": True,
        },
        "recommendations": {},
        "references": {},
        "note": {"portal_visible": True},
    }
    for i, (slug, extra) in enumerate(flags.items(), start=1):
        ContentSectionDefinition.objects.get_or_create(
            slug=slug,
            defaults={"label": slug.replace("-", " ").capitalize(), "order": i * 10, **extra},
        )


def setUpModule():
    seed_content_sections()


def section_content(obj, slug: str) -> str:
    return TemplateSection.objects.get(template=obj, definition__slug=slug).content


def finding_section_ciphertext(finding, slug: str) -> bytes:
    return bytes(FindingSection.objects.get(finding=finding, definition__slug=slug).content_ciphertext)


def decrypt_finding_section(finding, slug: str, key) -> str:
    from apps.crypto.services import decrypt_bytes, record_aad as _record_aad

    return decrypt_bytes(
        finding_section_ciphertext(finding, slug), key, associated_data=_record_aad("finding", finding.pk, slug),
    ).decode()


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    user = User.objects.create(
        role=Role.objects.get(slug=role.lower()), auth_type=User.AuthType.LOCAL, **kwargs
    )
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def login(client: Client, user) -> None:
    from django_otp import login as otp_login
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client.force_login(user)
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    session = client.session
    request = type("R", (), {"session": session, "user": user})()
    otp_login(request, device)
    session.save()


class CVSSVectorValidatorTests(TestCase):
    def test_blank_is_valid(self):
        validate_cvss_vector("")

    def test_valid_v3_1_base_only(self):
        validate_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")

    def test_valid_v3_1_with_optional_groups(self):
        validate_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:H/RL:O/RC:C/CR:H")

    def test_valid_v4_0_base_only(self):
        validate_cvss_vector("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N")

    def test_valid_v4_0_with_optional_groups(self):
        validate_cvss_vector(
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/E:A/U:Amber"
        )

    def test_unknown_header_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("CVSS:2.0/AV:N/AC:L/Au:N/C:C/I:C/A:C")

    def test_wrong_order_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("CVSS:3.1/AC:L/AV:N/PR:N/UI:N/S:U/C:H/I:H/A:H")

    def test_invalid_value_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("CVSS:3.1/AV:Z/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")

    def test_missing_base_metrics_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("CVSS:3.1/AV:N/AC:L")

    def test_duplicate_optional_metric_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:H/E:P")

    def test_garbage_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cvss_vector("not a vector")


class CVEIDValidatorTests(TestCase):
    def test_blank_is_valid(self):
        validate_cve_id("")

    def test_valid(self):
        validate_cve_id("CVE-2024-12345")

    def test_invalid_format_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cve_id("CVE-24-123")

    def test_missing_prefix_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cve_id("2024-12345")


class TiptapJsonValidatorTests(TestCase):
    def test_blank_is_valid(self):
        validate_tiptap_doc_json("")

    def test_valid_doc(self):
        validate_tiptap_doc_json(doc_json("hello"))

    def test_not_json_rejected(self):
        with self.assertRaises(ValidationError):
            validate_tiptap_doc_json("not json")

    def test_wrong_shape_rejected(self):
        with self.assertRaises(ValidationError):
            validate_tiptap_doc_json(json.dumps({"type": "paragraph"}))

    def test_non_object_rejected(self):
        with self.assertRaises(ValidationError):
            validate_tiptap_doc_json(json.dumps(["doc"]))


class ImageSrcSanitizerTests(TestCase):

    def _doc_with_image(self, src):
        return json.dumps({
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "before"}]},
                {"type": "image", "attrs": {"src": src}},
                {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
            ],
        })

    def test_own_blob_url_kept_when_allowed(self):
        from .validators import sanitize_tiptap_image_srcs

        eng_id = "a1b2c3d4-e5f6-4789-a1b2-c3d4e5f67890"
        blob_id = "11111111-2222-4333-8444-555555555555"
        src = f"/engagements/{eng_id}/blobs/{blob_id}/"
        result = json.loads(sanitize_tiptap_image_srcs(self._doc_with_image(src), allow_own_blobs=True))
        types = [n["type"] for n in result["content"]]
        self.assertIn("image", types)

    def test_external_url_stripped_even_when_own_blobs_allowed(self):
        from .validators import sanitize_tiptap_image_srcs

        result = json.loads(
            sanitize_tiptap_image_srcs(self._doc_with_image("https://evil.example/track.png"), allow_own_blobs=True)
        )
        types = [n["type"] for n in result["content"]]
        self.assertNotIn("image", types)
        self.assertEqual(len(types), 2)

    def test_data_uri_stripped(self):
        from .validators import sanitize_tiptap_image_srcs

        result = json.loads(
            sanitize_tiptap_image_srcs(self._doc_with_image("data:image/png;base64,iVBORw0KGgo="), allow_own_blobs=True)
        )
        self.assertNotIn("image", [n["type"] for n in result["content"]])

    def test_allow_own_blobs_false_strips_even_a_wellformed_blob_url(self):
        from .validators import sanitize_tiptap_image_srcs

        eng_id = "a1b2c3d4-e5f6-4789-a1b2-c3d4e5f67890"
        blob_id = "11111111-2222-4333-8444-555555555555"
        src = f"/engagements/{eng_id}/blobs/{blob_id}/"
        result = json.loads(sanitize_tiptap_image_srcs(self._doc_with_image(src), allow_own_blobs=False))
        self.assertNotIn("image", [n["type"] for n in result["content"]])

    def test_image_nested_inside_other_nodes_is_still_stripped(self):
        from .validators import sanitize_tiptap_image_srcs

        nested = json.dumps({
            "type": "doc",
            "content": [{"type": "blockquote", "content": [
                {"type": "paragraph", "content": [{"type": "image", "attrs": {"src": "https://evil.example/x.png"}}]},
            ]}],
        })
        result = json.loads(sanitize_tiptap_image_srcs(nested, allow_own_blobs=True))
        paragraph = result["content"][0]["content"][0]
        self.assertEqual(paragraph.get("content", []), [])

    def test_blank_and_malformed_input_pass_through_unchanged(self):
        from .validators import sanitize_tiptap_image_srcs

        self.assertEqual(sanitize_tiptap_image_srcs(""), "")
        self.assertEqual(sanitize_tiptap_image_srcs("not json"), "not json")


class FindingViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()

        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

        self.outsider = make_user(User.Role.CONSULTANT)

    def _form_data(self, **overrides):
        content_defaults = {
            "vulnerability_description": doc_json("The search field reflects unescaped input."),
            "business_impact": doc_json("Session hijacking."),
            "testing_summary": doc_json("Injected <script> payloads."),
            "technical_details": doc_json("GET /search?q=<script>alert(1)</script> reflects unsanitized."),
            "remediation_testing": doc_json("Retested 2026-08-01: payload no longer reflected."),
            "note": doc_json("Confirmed with two payloads."),
            "recommendations": doc_json("Contextually encode output."),
            "references": doc_json("https://owasp.org/www-community/attacks/xss/"),
        }
        data = {
            "title": "Reflected XSS in search",
            "cvss_score": "6.1",
            "cvss_vector": "",
            "severity": Finding.Severity.MEDIUM,
            "classification_taxonomy": [self.tag.taxonomy],
            "classification_value": [self.tag.value],
            "cve_id": "",
            "status": Finding.Status.OPEN,
            "affects": "https://app.acme.com/search",
        }
        for name in _CONTENT_FIELD_SLUGS:
            data[section_post_key(name)] = overrides.pop(name) if name in overrides else content_defaults[name]
        data.update(overrides)
        return data

    def test_member_can_create_finding_and_technical_details_encrypted_at_rest(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]), self._form_data()
        )
        self.assertEqual(resp.status_code, 302)

        finding = Finding.objects.get(title="Reflected XSS in search")
        self.assertEqual(finding.workflow_status, Finding.WorkflowStatus.DRAFT)
        self.assertEqual(finding.created_by, self.consultant)
        self.assertEqual(list(finding.classifications.all()), [self.tag])

        raw = finding_section_ciphertext(finding, "technical-details")
        self.assertNotIn(b"script", raw)

        key = get_data_key(self.engagement)
        plaintext = decrypt_finding_section(finding, "technical-details", key)
        self.assertIn("<script>alert(1)</script>", plaintext)
        self.assertEqual(json.loads(plaintext)["type"], "doc")

        note_plain = decrypt_finding_section(finding, "note", key)
        self.assertEqual(json.loads(note_plain)["content"][0]["content"][0]["text"], "Confirmed with two payloads.")

        raw_remediation = finding_section_ciphertext(finding, "remediation-testing")
        self.assertNotIn(b"Retested", raw_remediation)
        remediation_plain = decrypt_finding_section(finding, "remediation-testing", key)
        self.assertIn("Retested 2026-08-01", remediation_plain)

    def test_new_finding_auto_assigned_when_engagement_already_in_review(self):
        reviewer = make_user(User.Role.SENIOR)
        self.engagement.default_reviewer = reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        self.assertEqual(resp.status_code, 302)

        finding = Finding.objects.get(title="Reflected XSS in search")
        self.assertEqual(finding.assigned_reviewer, reviewer)

    def test_no_auto_assign_when_engagement_not_in_review(self):
        reviewer = make_user(User.Role.SENIOR)
        self.engagement.default_reviewer = reviewer
        self.engagement.save(update_fields=["default_reviewer"])

        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())

        finding = Finding.objects.get(title="Reflected XSS in search")
        self.assertIsNone(finding.assigned_reviewer)

    def test_remediation_testing_is_optional(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]),
            self._form_data(remediation_testing=""),
        )
        self.assertEqual(resp.status_code, 302)

        finding = Finding.objects.get(title="Reflected XSS in search")
        key = get_data_key(self.engagement)
        self.assertEqual(decrypt_finding_section(finding, "remediation-testing", key), "")

    def test_base_template_comment_does_not_leak_into_rendered_page(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        self.assertNotContains(resp, "main_class defaults")

    def test_non_member_cannot_create_finding(self):
        client = Client()
        login(client, self.outsider)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]), self._form_data()
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Finding.objects.filter(title="Reflected XSS in search").exists())

    def test_classification_required(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]),
            self._form_data(classification_taxonomy=[], classification_value=[]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Finding.objects.filter(title="Reflected XSS in search").exists())

    def test_classification_row_needs_both_taxonomy_and_value(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]),
            self._form_data(classification_taxonomy=[""], classification_value=["A03:2021 - Injection"]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Finding.objects.filter(title="Reflected XSS in search").exists())

    def test_taxonomy_is_not_hardcoded(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]),
            self._form_data(
                classification_taxonomy=["OWASP Top 10 2025"],
                classification_value=["A01:2025 - Broken Access Control"],
            ),
        )
        self.assertEqual(resp.status_code, 302)

        finding = Finding.objects.get(title="Reflected XSS in search")
        tag = finding.classifications.get()
        self.assertEqual(tag.taxonomy, "OWASP Top 10 2025")
        self.assertEqual(tag.value, "A01:2025 - Broken Access Control")

    def test_detail_view_decrypts_all_sections(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")

        resp = client.get(reverse("findings:detail", args=[self.engagement.pk, finding.pk]))
        self.assertEqual(resp.status_code, 200)
        by_slug = {s["field_name"]: s["content_json"] for s in resp.context["document_sections"]}
        self.assertIn("<script>alert(1)</script>", by_slug["technical-details"])
        self.assertIn("Retested 2026-08-01", by_slug["remediation-testing"])
        self.assertIn("Confirmed with two payloads.", by_slug["note"])

    def test_non_member_cannot_view_finding(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")

        outsider_client = Client()
        login(outsider_client, self.outsider)
        resp = outsider_client.get(reverse("findings:detail", args=[self.engagement.pk, finding.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_edit_reencrypts_and_updates_plain_fields(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")

        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, finding.pk]),
            self._form_data(
                title="Reflected XSS in search (confirmed)",
                technical_details=doc_json("updated payload details"),
            ),
        )
        self.assertEqual(resp.status_code, 302)

        finding.refresh_from_db()
        self.assertEqual(finding.title, "Reflected XSS in search (confirmed)")
        key = get_data_key(self.engagement)
        plaintext = decrypt_finding_section(finding, "technical-details", key)
        self.assertIn("updated payload details", plaintext)

    def test_deactivating_a_section_does_not_wipe_its_existing_content_on_edit(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")
        key = get_data_key(self.engagement)
        original_note = decrypt_finding_section(finding, "note", key)

        note_definition = ContentSectionDefinition.objects.get(slug="note")
        note_definition.is_active = False
        note_definition.save()
        try:
            data = self._form_data(title="Reflected XSS in search (edited)")
            resp = client.post(reverse("findings:edit", args=[self.engagement.pk, finding.pk]), data)
            self.assertEqual(resp.status_code, 302)
        finally:
            note_definition.is_active = True
            note_definition.save()

        finding.refresh_from_db()
        self.assertEqual(finding.title, "Reflected XSS in search (edited)")
        surviving_note = decrypt_finding_section(finding, "note", key)
        self.assertEqual(surviving_note, original_note)

    def test_invalid_cvss_vector_rejected_on_create(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:create", args=[self.engagement.pk]),
            self._form_data(cvss_vector="garbage"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Finding.objects.filter(title="Reflected XSS in search").exists())

    def test_edit_rejected_when_version_stale(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")
        stale_version = finding.updated_at.isoformat()

        finding.title = "Touched by someone else"
        finding.save()

        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, finding.pk]),
            self._form_data(title="Attempted overwrite", _version=stale_version),
        )
        self.assertEqual(resp.status_code, 200)

        finding.refresh_from_db()
        self.assertEqual(finding.title, "Touched by someone else")

    def test_edit_succeeds_with_matching_version(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")
        current_version = finding.updated_at.isoformat()

        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, finding.pk]),
            self._form_data(title="Updated title", _version=current_version),
        )
        self.assertEqual(resp.status_code, 302)

        finding.refresh_from_db()
        self.assertEqual(finding.title, "Updated title")

    def test_edit_without_version_field_still_saves(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")

        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, finding.pk]),
            self._form_data(title="Updated without version"),
        )
        self.assertEqual(resp.status_code, 302)
        finding.refresh_from_db()
        self.assertEqual(finding.title, "Updated without version")

    def test_edit_saves_when_finding_has_zero_classifications(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("findings:create", args=[self.engagement.pk]), self._form_data())
        finding = Finding.objects.get(title="Reflected XSS in search")
        finding.classifications.clear()
        self.assertEqual(finding.classifications.count(), 0)

        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, finding.pk]),
            self._form_data(
                title="Updated with zero classifications",
                classification_taxonomy=[], classification_value=[],
            ),
        )
        self.assertEqual(resp.status_code, 302)
        finding.refresh_from_db()
        self.assertEqual(finding.title, "Updated with zero classifications")
        self.assertEqual(finding.classifications.count(), 0)


class OwaspTop10SeedTests(TestCase):

    def test_both_owasp_editions_present_and_distinct(self):
        self.assertEqual(ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").count(), 10)
        self.assertEqual(ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2025").count(), 10)
        self.assertFalse(ClassificationTag.objects.filter(taxonomy="OWASP Top 10").exists())

    def test_2025_categories_match_official_list(self):
        values = set(
            ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2025").values_list("value", flat=True)
        )
        self.assertIn("A01:2025 – Broken Access Control", values)
        self.assertIn("A05:2025 – Injection", values)
        self.assertIn("A10:2025 – Mishandling of Exceptional Conditions", values)

    def test_2021_values_unchanged(self):
        values = set(
            ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").values_list("value", flat=True)
        )
        self.assertIn("A03:2021 – Injection", values)


class CommentThreadTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()

        self.author = make_user(User.Role.CONSULTANT)
        self.reviewer = make_user(User.Role.TEAM_LEAD)
        self.outsider = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.author, engagement=self.engagement)

        self.finding = Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.author,
        )
        key = get_data_key(self.engagement)
        FindingSection.objects.create(
            finding=self.finding, definition=ContentSectionDefinition.objects.get(slug="technical-details"),
            content_ciphertext=encrypt_bytes(
                doc_json("The login endpoint concatenates user input into a SQL query.").encode(), key,
                associated_data=record_aad("finding", self.finding.pk, "technical-details"),
            ),
        )
        self.finding.classifications.add(self.tag)

    def _create_url(self):
        return reverse("findings:comment_thread_create", args=[self.engagement.pk, self.finding.pk, "technical-details"])

    def _list_url(self):
        return reverse("findings:comment_thread_list", args=[self.engagement.pk, self.finding.pk, "technical-details"])

    def test_member_can_create_thread_and_body_encrypted_at_rest(self):
        client = Client()
        login(client, self.reviewer)
        resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "concatenates", "body": "Use parameterized queries here."}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

        thread = CommentThread.objects.get(finding=self.finding)
        self.assertEqual(thread.field_name, "technical-details")
        self.assertEqual(thread.created_by, self.reviewer)
        self.assertFalse(thread.resolved)

        entry = CommentEntry.objects.get(thread=thread)
        raw = bytes(entry.body_ciphertext)
        self.assertNotIn(b"parameterized", raw)

        key = get_data_key(self.engagement)
        self.assertEqual(
            decrypt_bytes(raw, key, associated_data=record_aad("commententry", entry.pk, "body")).decode(),
            "Use parameterized queries here.",
        )

        raw_anchor = bytes(thread.anchored_text_ciphertext)
        self.assertNotIn(b"concatenates", raw_anchor)
        self.assertEqual(
            decrypt_bytes(
                raw_anchor, key, associated_data=record_aad("commentthread", thread.pk, "anchored_text"),
            ).decode(),
            "concatenates",
        )

    def test_non_member_cannot_create_thread(self):
        client = Client()
        login(client, self.outsider)
        resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "x", "body": "y"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(CommentThread.objects.exists())

    def test_list_decrypts_thread_and_entries(self):
        client = Client()
        login(client, self.author)
        client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "concatenates", "body": "flag this"}),
            content_type="application/json",
        )
        resp = client.get(self._list_url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["threads"]), 1)
        self.assertEqual(data["threads"][0]["anchored_text"], "concatenates")
        self.assertEqual(data["threads"][0]["entries"][0]["body"], "flag this")

    def test_reply_appends_entry(self):
        client = Client()
        login(client, self.author)
        create_resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "x", "body": "first"}),
            content_type="application/json",
        )
        thread_id = create_resp.json()["id"]

        reply_url = reverse("findings:comment_thread_reply", args=[self.engagement.pk, self.finding.pk, thread_id])
        resp = client.post(reply_url, data=json.dumps({"body": "second"}), content_type="application/json")
        self.assertEqual(resp.status_code, 201)

        thread = CommentThread.objects.get(pk=thread_id)
        self.assertEqual(thread.entries.count(), 2)

    def test_resolve_toggles(self):
        client = Client()
        login(client, self.author)
        create_resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "x", "body": "first"}),
            content_type="application/json",
        )
        thread_id = create_resp.json()["id"]
        resolve_url = reverse("findings:comment_thread_resolve", args=[self.engagement.pk, self.finding.pk, thread_id])

        resp = client.post(resolve_url)
        self.assertTrue(resp.json()["resolved"])
        resp = client.post(resolve_url)
        self.assertFalse(resp.json()["resolved"])

    def test_invalid_range_rejected(self):
        client = Client()
        login(client, self.author)
        resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 10, "end_pos": 5, "anchored_text": "x", "body": "y"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def _create_thread(self, client):
        resp = client.post(
            self._create_url(),
            data=json.dumps({"start_pos": 1, "end_pos": 10, "anchored_text": "x", "body": "first"}),
            content_type="application/json",
        )
        return resp.json()["id"]

    def _delete_url(self, thread_id):
        return reverse("findings:comment_thread_delete", args=[self.engagement.pk, self.finding.pk, thread_id])

    def test_creator_can_delete_own_thread(self):
        client = Client()
        login(client, self.author)
        thread_id = self._create_thread(client)

        resp = client.post(self._delete_url(thread_id))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CommentThread.objects.filter(pk=thread_id).exists())
        self.assertFalse(CommentEntry.objects.filter(thread_id=thread_id).exists())

    def test_manager_can_delete_someone_elses_thread(self):
        client = Client()
        login(client, self.author)
        thread_id = self._create_thread(client)

        manager_client = Client()
        login(manager_client, self.reviewer)
        resp = manager_client.post(self._delete_url(thread_id))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CommentThread.objects.filter(pk=thread_id).exists())

    def test_non_creator_non_manager_cannot_delete_thread(self):
        other_member = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=other_member, engagement=self.engagement)

        client = Client()
        login(client, self.author)
        thread_id = self._create_thread(client)

        other_client = Client()
        login(other_client, other_member)
        resp = other_client.post(self._delete_url(thread_id))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(CommentThread.objects.filter(pk=thread_id).exists())

    def test_list_includes_can_delete_flag(self):
        client = Client()
        login(client, self.author)
        self._create_thread(client)

        other_member = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=other_member, engagement=self.engagement)
        other_client = Client()
        login(other_client, other_member)

        self.assertTrue(client.get(self._list_url()).json()["threads"][0]["can_delete"])
        self.assertFalse(other_client.get(self._list_url()).json()["threads"][0]["can_delete"])


class CatalogueTests(TestCase):
    def setUp(self):
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        self.senior = make_user(User.Role.SENIOR)

        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

    def _template_form_data(self, **overrides):
        content_defaults = {
            "vulnerability_description": doc_json("Generic XSS description."),
            "business_impact": doc_json("Generic impact."),
            "testing_summary": doc_json("Generic testing approach."),
            "technical_details": doc_json("Example: <script>alert(1)</script>"),
            "recommendations": doc_json("Encode output contextually."),
            "references": doc_json("https://owasp.org/www-community/attacks/xss/"),
        }
        data = {
            "title": "Reflected XSS",
            "default_cvss_score": "6.1",
            "default_cvss_vector": "",
            "default_severity": Finding.Severity.MEDIUM,
            "classification_taxonomy": [self.tag.taxonomy],
            "classification_value": [self.tag.value],
        }
        for name in content_defaults:
            data[section_post_key(name)] = overrides.pop(name) if name in overrides else content_defaults[name]
        data.update(overrides)
        return data

    def test_team_lead_can_create_template(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(reverse("catalogue:create"), self._template_form_data())
        self.assertEqual(resp.status_code, 302)
        template = VulnerabilityTemplate.objects.get(title="Reflected XSS")
        self.assertEqual(template.created_by, self.team_lead)
        self.assertEqual(list(template.classifications.all()), [self.tag])
        self.assertIn("<script>alert(1)</script>", section_content(template, "technical-details"))

    def test_catalogue_form_strips_any_image_node(self):
        doc_with_image = json.dumps({
            "type": "doc",
            "content": [{"type": "image", "attrs": {"src": "/engagements/x/blobs/y/"}}],
        })
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("catalogue:create"),
            self._template_form_data(vulnerability_description=doc_with_image),
        )
        self.assertEqual(resp.status_code, 302)
        template = VulnerabilityTemplate.objects.get(title="Reflected XSS")
        self.assertNotIn("image", section_content(template, "vulnerability-description"))

    def test_any_authenticated_user_can_create_template_as_draft(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:create"), self._template_form_data())
        self.assertEqual(resp.status_code, 302)
        template = VulnerabilityTemplate.objects.get(title="Reflected XSS")
        self.assertEqual(template.created_by, self.consultant)
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_any_authenticated_user_can_browse_catalogue(self):
        VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH,
        )
        client = Client()
        login(client, self.senior)
        resp = client.get(reverse("catalogue:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SSRF")

    def test_search_filters_by_title(self):
        VulnerabilityTemplate.objects.create(title="SSRF", default_severity=Finding.Severity.HIGH)
        VulnerabilityTemplate.objects.create(title="SQL Injection", default_severity=Finding.Severity.CRITICAL)
        client = Client()
        login(client, self.senior)
        resp = client.get(reverse("catalogue:list"), {"q": "SSRF"})
        titles = [t.title for t in resp.context["page_obj"].object_list]
        self.assertEqual(titles, ["SSRF"])

    def test_pagination_caps_at_ten_per_page(self):
        for i in range(12):
            VulnerabilityTemplate.objects.create(title=f"Template {i}", default_severity=Finding.Severity.LOW)
        client = Client()
        login(client, self.senior)
        resp = client.get(reverse("catalogue:list"))
        page_obj = resp.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertEqual(page_obj.paginator.num_pages, 2)

    def test_consultant_cannot_edit_or_delete_someone_elses_template(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.team_lead,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:edit", args=[template.pk]), self._template_form_data())
        self.assertEqual(resp.status_code, 403)
        resp = client.post(reverse("catalogue:delete", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(VulnerabilityTemplate.objects.filter(pk=template.pk).exists())

    def test_creator_can_edit_own_draft_template(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("catalogue:edit", args=[template.pk]),
            self._template_form_data(title="SSRF (updated)"),
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.title, "SSRF (updated)")

    def test_creator_can_edit_own_approved_template_and_it_reverts_to_draft(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("catalogue:edit", args=[template.pk]),
            self._template_form_data(title="SSRF (updated)"),
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.title, "SSRF (updated)")
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_deactivating_a_template_section_does_not_wipe_its_existing_content_on_edit(self):
        client = Client()
        login(client, self.consultant)
        client.post(reverse("catalogue:create"), self._template_form_data())
        template = VulnerabilityTemplate.objects.get(title="Reflected XSS")
        original_business_impact = section_content(template, "business-impact")

        definition = ContentSectionDefinition.objects.get(slug="business-impact")
        definition.is_active = False
        definition.save()
        try:
            data = self._template_form_data(title="Reflected XSS (edited)")
            resp = client.post(reverse("catalogue:edit", args=[template.pk]), data)
            self.assertEqual(resp.status_code, 302)
        finally:
            definition.is_active = True
            definition.save()

        template.refresh_from_db()
        self.assertEqual(template.title, "Reflected XSS (edited)")
        self.assertEqual(section_content(template, "business-impact"), original_business_impact)

    def test_team_lead_editing_approved_template_also_reverts_to_draft(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("catalogue:edit", args=[template.pk]),
            self._template_form_data(title="SSRF (fixed by lead)"),
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.title, "SSRF (fixed by lead)")
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_editing_draft_template_does_not_touch_status(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("catalogue:edit", args=[template.pk]),
            self._template_form_data(title="SSRF (still draft)"),
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_creator_can_delete_own_template_regardless_of_status(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:delete", args=[template.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VulnerabilityTemplate.objects.filter(pk=template.pk).exists())

    def test_team_lead_can_delete_anyones_template(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(reverse("catalogue:delete", args=[template.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VulnerabilityTemplate.objects.filter(pk=template.pk).exists())

    def test_senior_cannot_delete_someone_elses_template(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.senior)
        resp = client.post(reverse("catalogue:delete", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(VulnerabilityTemplate.objects.filter(pk=template.pk).exists())

    def test_senior_and_team_lead_can_approve_draft(self):
        for approver_attr in ("senior", "team_lead"):
            with self.subTest(approver=approver_attr):
                template = VulnerabilityTemplate.objects.create(
                    title=f"SSRF {approver_attr}", default_severity=Finding.Severity.HIGH,
                    created_by=self.consultant,
                )
                client = Client()
                login(client, getattr(self, approver_attr))
                resp = client.post(reverse("catalogue:approve", args=[template.pk]))
                self.assertEqual(resp.status_code, 302)
                template.refresh_from_db()
                self.assertEqual(template.status, VulnerabilityTemplate.Status.APPROVED)

    def test_consultant_cannot_approve_draft(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:approve", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_senior_and_team_lead_can_revert_approved_to_draft(self):
        for approver_attr in ("senior", "team_lead"):
            with self.subTest(approver=approver_attr):
                template = VulnerabilityTemplate.objects.create(
                    title=f"SSRF {approver_attr}", default_severity=Finding.Severity.HIGH,
                    created_by=self.consultant, status=VulnerabilityTemplate.Status.APPROVED,
                )
                client = Client()
                login(client, getattr(self, approver_attr))
                resp = client.post(reverse("catalogue:unapprove", args=[template.pk]))
                self.assertEqual(resp.status_code, 302)
                template.refresh_from_db()
                self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_consultant_cannot_unapprove(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:unapprove", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.APPROVED)

    def test_consultant_can_submit_own_draft_for_qa(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:submit_qa", args=[template.pk]))
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.PENDING_QA)

    def test_consultant_cannot_submit_someone_elses_draft_for_qa(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.team_lead,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:submit_qa", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_consultant_cannot_approve_pending_qa_entry(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.PENDING_QA,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("catalogue:approve", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.PENDING_QA)

    def test_senior_and_team_lead_can_approve_pending_qa_entry(self):
        for approver_attr in ("senior", "team_lead"):
            with self.subTest(approver=approver_attr):
                template = VulnerabilityTemplate.objects.create(
                    title=f"SSRF {approver_attr}", default_severity=Finding.Severity.HIGH,
                    created_by=self.consultant, status=VulnerabilityTemplate.Status.PENDING_QA,
                )
                client = Client()
                login(client, getattr(self, approver_attr))
                resp = client.post(reverse("catalogue:approve", args=[template.pk]))
                self.assertEqual(resp.status_code, 302)
                template.refresh_from_db()
                self.assertEqual(template.status, VulnerabilityTemplate.Status.APPROVED)

    def test_senior_can_send_pending_qa_entry_back_to_draft(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.PENDING_QA,
        )
        client = Client()
        login(client, self.senior)
        resp = client.post(reverse("catalogue:unapprove", args=[template.pk]))
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_editing_pending_qa_entry_reverts_it_to_draft(self):
        template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH, created_by=self.consultant,
            status=VulnerabilityTemplate.Status.PENDING_QA,
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("catalogue:edit", args=[template.pk]),
            self._template_form_data(title="SSRF (edited)"),
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.status, VulnerabilityTemplate.Status.DRAFT)

    def test_copy_to_engagement_prefills_form_and_has_no_link_back(self):
        template = VulnerabilityTemplate.objects.create(
            title="Reflected XSS",
            default_severity=Finding.Severity.MEDIUM,
            default_cvss_score="6.1",
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        for slug, text in [
            ("vulnerability-description", "Generic XSS description."),
            ("technical-details", "Example payload here."),
            ("references", "https://owasp.org/www-community/attacks/xss/"),
        ]:
            TemplateSection.objects.create(
                template=template, definition=ContentSectionDefinition.objects.get(slug=slug),
                content=doc_json(text),
            )
        template.classifications.add(self.tag)

        client = Client()
        login(client, self.consultant)

        resp = client.get(
            reverse("findings:create", args=[self.engagement.pk]), {"from_template": template.pk}
        )
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        self.assertEqual(form.initial["title"], "Reflected XSS")
        self.assertEqual(form.initial["cvss_score"], "6.1")
        self.assertIn("Generic XSS description.", form.initial[section_post_key("vulnerability_description")])

        data = {
            "title": "Reflected XSS",
            "cvss_score": "6.1",
            "cvss_vector": "",
            "severity": Finding.Severity.MEDIUM,
            "classification_taxonomy": [self.tag.taxonomy],
            "classification_value": [self.tag.value],
            "cve_id": "",
            "status": Finding.Status.OPEN,
            "affects": "https://app.acme.com/search",
        }
        content = {
            "vulnerability_description": doc_json("Generic XSS description."),
            "business_impact": doc_json(""),
            "testing_summary": doc_json(""),
            "technical_details": doc_json("Example payload here."),
            "note": "",
            "remediation_testing": "",
            "recommendations": doc_json(""),
            "references": doc_json("https://owasp.org/www-community/attacks/xss/"),
        }
        for name, value in content.items():
            data[section_post_key(name)] = value
        resp = client.post(reverse("findings:create", args=[self.engagement.pk]), data)
        self.assertEqual(resp.status_code, 302)

        finding = Finding.objects.get(title="Reflected XSS")
        self.assertFalse(hasattr(finding, "vulnerability_template"))
        self.assertNotIn("template", [f.name for f in Finding._meta.get_fields()])

        template.title = "Renamed template"
        template.save()
        template.delete()
        finding.refresh_from_db()
        self.assertEqual(finding.title, "Reflected XSS")

    def test_create_without_from_template_is_blank(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:create", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["form"].initial.get("title"))


class CatalogueVersioningTests(TestCase):
    def setUp(self):
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        self.senior = make_user(User.Role.SENIOR)

        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

        self.template = VulnerabilityTemplate.objects.create(
            title="Reflected XSS", default_severity=Finding.Severity.MEDIUM, default_cvss_score="6.1",
            created_by=self.consultant, status=VulnerabilityTemplate.Status.PENDING_QA,
        )
        TemplateSection.objects.create(
            template=self.template,
            definition=ContentSectionDefinition.objects.get(slug="vulnerability-description"),
            content=doc_json("Generic XSS description."),
        )
        self.template.classifications.add(self.tag)

    def _approve(self):
        client = Client()
        login(client, self.senior)
        resp = client.post(reverse("catalogue:approve", args=[self.template.pk]))
        self.assertEqual(resp.status_code, 302)

    def _import_initial(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(
            reverse("findings:create", args=[self.engagement.pk]), {"from_template": self.template.pk}
        )
        self.assertEqual(resp.status_code, 200)
        return resp.context["form"].initial

    def test_approving_creates_a_snapshot(self):
        self._approve()
        version = VulnerabilityTemplateApprovedVersion.objects.get(template=self.template)
        self.assertEqual(version.title, "Reflected XSS")
        self.assertEqual(version.approved_by, self.senior)
        self.assertIn("vulnerability-description", version.sections)

    def test_unapproved_template_cannot_be_imported(self):
        self.assertIsNone(self._import_initial().get("title"))

    def test_approved_template_can_be_imported_with_live_content(self):
        self._approve()
        self.assertEqual(self._import_initial()["title"], "Reflected XSS")

    def test_editing_approved_template_drops_to_draft_but_last_approved_version_still_imports(self):
        self._approve()

        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("catalogue:edit", args=[self.template.pk]),
            {"title": "Reflected XSS (unvetted rewrite)", "default_severity": Finding.Severity.MEDIUM},
        )
        self.assertEqual(resp.status_code, 302)
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, VulnerabilityTemplate.Status.DRAFT)
        self.assertEqual(self.template.title, "Reflected XSS (unvetted rewrite)")

        # The live row now holds the unvetted rewrite, but importing still pulls the version
        # that was actually approved — not the pending edit.
        self.assertEqual(self._import_initial()["title"], "Reflected XSS")

    def test_unapprove_revokes_the_snapshot_and_blocks_import(self):
        self._approve()

        client = Client()
        login(client, self.senior)
        resp = client.post(reverse("catalogue:unapprove", args=[self.template.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VulnerabilityTemplateApprovedVersion.objects.filter(template=self.template).exists())

        self.assertIsNone(self._import_initial().get("title"))

    def test_reapproving_replaces_the_snapshot(self):
        self._approve()
        first_version_id = VulnerabilityTemplateApprovedVersion.objects.get(template=self.template).pk

        client = Client()
        login(client, self.consultant)
        client.post(
            reverse("catalogue:edit", args=[self.template.pk]),
            {"title": "Reflected XSS v2", "default_severity": Finding.Severity.MEDIUM},
        )
        self._approve()

        version = VulnerabilityTemplateApprovedVersion.objects.get(template=self.template)
        self.assertEqual(version.pk, first_version_id)
        self.assertEqual(version.title, "Reflected XSS v2")
        self.assertEqual(self._import_initial()["title"], "Reflected XSS v2")


class CatalogueExportImportTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
        self.template = VulnerabilityTemplate.objects.create(
            title="SSRF", default_severity=Finding.Severity.HIGH,
            default_cvss_score="8.6", default_cvss_vector="",
            status=VulnerabilityTemplate.Status.APPROVED,
        )
        TemplateSection.objects.create(
            template=self.template, definition=ContentSectionDefinition.objects.get(slug="vulnerability-description"),
            content=doc_json("Server makes an attacker-controlled request."),
        )
        self.template.classifications.add(self.tag)

    def test_export_then_import_round_trips_content(self):
        from apps.findings.catalogue_io import export_templates, import_templates

        payload = export_templates(VulnerabilityTemplate.objects.all())
        created = import_templates(payload, created_by=self.superadmin)

        self.assertEqual(len(created), 1)
        imported = created[0]
        self.assertEqual(imported.title, "SSRF")
        self.assertEqual(imported.default_severity, Finding.Severity.HIGH)
        self.assertEqual(imported.default_cvss_score, "8.6")
        self.assertIn(
            "Server makes an attacker-controlled request.", section_content(imported, "vulnerability-description"),
        )
        self.assertEqual({(t.taxonomy, t.value) for t in imported.classifications.all()}, {(self.tag.taxonomy, self.tag.value)})

    def test_import_always_creates_draft_regardless_of_exported_status(self):
        from apps.findings.catalogue_io import export_templates, import_templates

        payload = export_templates(VulnerabilityTemplate.objects.all())
        created = import_templates(payload, created_by=self.superadmin)
        self.assertEqual(created[0].status, VulnerabilityTemplate.Status.DRAFT)

    def test_import_rejects_missing_title(self):
        from apps.findings.catalogue_io import CatalogueImportError, import_templates

        with self.assertRaises(CatalogueImportError):
            import_templates('[{"default_severity": "HIGH"}]', created_by=self.superadmin)
        self.assertEqual(VulnerabilityTemplate.objects.count(), 1)

    def test_import_rejects_invalid_severity(self):
        from apps.findings.catalogue_io import CatalogueImportError, import_templates

        with self.assertRaises(CatalogueImportError):
            import_templates('[{"title": "X", "default_severity": "NOT_REAL"}]', created_by=self.superadmin)

    def test_import_is_all_or_nothing(self):
        from apps.findings.catalogue_io import CatalogueImportError, import_templates

        payload = (
            '[{"title": "Good one", "default_severity": "LOW"}, '
            '{"title": "Bad one", "default_severity": "NOT_REAL"}]'
        )
        with self.assertRaises(CatalogueImportError):
            import_templates(payload, created_by=self.superadmin)
        self.assertFalse(VulnerabilityTemplate.objects.filter(title="Good one").exists())

    def test_import_rejects_malformed_json(self):
        from apps.findings.catalogue_io import CatalogueImportError, import_templates

        with self.assertRaises(CatalogueImportError):
            import_templates("not json at all", created_by=self.superadmin)

    def test_import_rejects_non_list_top_level(self):
        from apps.findings.catalogue_io import CatalogueImportError, import_templates

        with self.assertRaises(CatalogueImportError):
            import_templates('{"title": "X"}', created_by=self.superadmin)

    def test_import_accepts_plain_text_rich_fields(self):
        from apps.findings.catalogue_io import import_templates

        payload = json.dumps([{
            "title": "Plain text entry", "default_severity": "LOW",
            "sections": {"vulnerability-description": "Just plain text."},
        }])
        created = import_templates(payload, created_by=self.superadmin)
        content = section_content(created[0], "vulnerability-description")
        self.assertIn("Just plain text.", content)
        self.assertIn('"type": "doc"', content)

    def test_non_superadmin_cannot_export(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.get(reverse("catalogue:export"))
        self.assertEqual(resp.status_code, 403)

    def test_non_superadmin_cannot_reach_import_page(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.get(reverse("catalogue:import"))
        self.assertEqual(resp.status_code, 403)

    def test_superadmin_can_export(self):
        client = Client()
        login(client, self.superadmin)
        resp = client.get(reverse("catalogue:export"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = json.loads(resp.content)
        self.assertEqual(body[0]["title"], "SSRF")

    def test_superadmin_can_import_via_http(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        payload = '[{"title": "Uploaded entry", "default_severity": "MEDIUM"}]'
        upload = SimpleUploadedFile("catalogue.json", payload.encode(), content_type="application/json")

        client = Client()
        login(client, self.superadmin)
        resp = client.post(reverse("catalogue:import"), {"file": upload})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(VulnerabilityTemplate.objects.filter(title="Uploaded entry").exists())

    def test_invalid_upload_shows_error_without_creating_anything(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("catalogue.json", b"not json", content_type="application/json")
        client = Client()
        login(client, self.superadmin)
        resp = client.post(reverse("catalogue:import"), {"file": upload})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid JSON")
        self.assertEqual(VulnerabilityTemplate.objects.count(), 1)


def make_finding(engagement, created_by, **kwargs):
    tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
    key = get_data_key(engagement)
    finding = Finding.objects.create(
        engagement=engagement,
        title=kwargs.pop("title", "Test finding"),
        severity=kwargs.pop("severity", Finding.Severity.HIGH),
        created_by=created_by,
        **kwargs,
    )
    finding.classifications.add(tag)
    FindingSection.objects.create(
        finding=finding, definition=ContentSectionDefinition.objects.get(slug="technical-details"),
        content_ciphertext=encrypt_bytes(
            doc_json("details").encode(), key,
            associated_data=record_aad("finding", finding.pk, "technical-details"),
        ),
    )
    return finding


class FindingListOrderingTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

    def test_findings_ordered_by_cvss_score_descending(self):
        low = make_finding(self.engagement, self.consultant, title="Low", cvss_score="3.1")
        critical = make_finding(self.engagement, self.consultant, title="Critical", cvss_score="9.8")
        medium = make_finding(self.engagement, self.consultant, title="Medium", cvss_score="5.4")

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        titles = [f.title for f in resp.context["findings"]]
        self.assertEqual(titles, [critical.title, medium.title, low.title])

    def test_non_numeric_or_blank_scores_sort_after_numeric_ones(self):
        blank = make_finding(self.engagement, self.consultant, title="Blank", cvss_score="")
        wordy = make_finding(self.engagement, self.consultant, title="Wordy", cvss_score="High")
        scored = make_finding(self.engagement, self.consultant, title="Scored", cvss_score="4.0")

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        titles = [f.title for f in resp.context["findings"]]
        self.assertEqual(titles[0], scored.title)
        self.assertEqual(set(titles[1:]), {blank.title, wordy.title})

    def test_search_filters_by_title_or_cve_id(self):
        make_finding(self.engagement, self.consultant, title="SQL Injection", cvss_score="9.8")
        make_finding(self.engagement, self.consultant, title="Reflected XSS", cvss_score="6.1", cve_id="CVE-2024-1234")
        make_finding(self.engagement, self.consultant, title="Unrelated", cvss_score="2.0")

        client = Client()
        login(client, self.consultant)

        resp = client.get(reverse("findings:list", args=[self.engagement.pk]), {"q": "Injection"})
        self.assertEqual([f.title for f in resp.context["findings"]], ["SQL Injection"])

        resp = client.get(reverse("findings:list", args=[self.engagement.pk]), {"q": "CVE-2024-1234"})
        self.assertEqual([f.title for f in resp.context["findings"]], ["Reflected XSS"])

    def test_pagination_caps_at_ten_per_page(self):
        for i in range(12):
            make_finding(self.engagement, self.consultant, title=f"Finding {i}", cvss_score=str(i))

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        page_obj = resp.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertEqual(page_obj.paginator.num_pages, 2)

    def test_assigned_reviewer_and_qa_shown_in_list(self):
        senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=senior, engagement=self.engagement)
        finding = make_finding(self.engagement, self.consultant, title="Assigned one")
        review.assign_reviewer(finding, senior, assigned_by=self.consultant)

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        self.assertContains(resp, f"Reviewer: {senior}")

        review.submit_review(finding, senior, Finding.WorkflowStatus.REVIEWED)
        qa_person = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=qa_person, engagement=self.engagement)
        review.assign_qa(finding, qa_person, assigned_by=self.consultant)
        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        self.assertContains(resp, f"QA: {qa_person}")


class FindingArchiveViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant, title="Old finding")

    def test_team_lead_can_archive_and_unarchive(self):
        client = Client()
        login(client, self.team_lead)

        resp = client.post(reverse("findings:archive", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertTrue(self.finding.archived)
        self.assertIsNotNone(self.finding.archived_at)

        resp = client.post(reverse("findings:unarchive", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertFalse(self.finding.archived)
        self.assertIsNone(self.finding.archived_at)

    def test_consultant_can_archive_own_finding(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("findings:archive", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertTrue(self.finding.archived)

    def test_consultant_can_unarchive_own_finding(self):
        self.finding.archived = True
        self.finding.save(update_fields=["archived"])
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("findings:unarchive", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertFalse(self.finding.archived)

    def test_consultant_cannot_archive_someone_elses_finding(self):
        other_consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=other_consultant, engagement=self.engagement)
        others_finding = make_finding(self.engagement, other_consultant, title="Someone else's finding")

        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("findings:archive", args=[self.engagement.pk, others_finding.pk]))
        self.assertEqual(resp.status_code, 403)
        others_finding.refresh_from_db()
        self.assertFalse(others_finding.archived)

    def test_consultant_cannot_unarchive_someone_elses_finding(self):
        other_consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=other_consultant, engagement=self.engagement)
        others_finding = make_finding(self.engagement, other_consultant, title="Someone else's finding")
        others_finding.archived = True
        others_finding.save(update_fields=["archived"])

        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("findings:unarchive", args=[self.engagement.pk, others_finding.pk]))
        self.assertEqual(resp.status_code, 403)
        others_finding.refresh_from_db()
        self.assertTrue(others_finding.archived)

    def test_archived_finding_hidden_from_default_list_but_shown_when_toggled(self):
        self.finding.archived = True
        self.finding.save(update_fields=["archived"])
        active = make_finding(self.engagement, self.consultant, title="Active finding")

        client = Client()
        login(client, self.consultant)

        resp = client.get(reverse("findings:list", args=[self.engagement.pk]))
        self.assertEqual([f.title for f in resp.context["findings"]], [active.title])
        self.assertEqual(resp.context["archived_count"], 1)

        resp = client.get(reverse("findings:list", args=[self.engagement.pk]), {"archived": "1"})
        titles = {f.title for f in resp.context["findings"]}
        self.assertEqual(titles, {active.title, self.finding.title})

    def test_archived_finding_cannot_be_edited(self):
        self.finding.archived = True
        self.finding.save(update_fields=["archived"])
        self.assertFalse(can_edit_finding_content(self.consultant, self.finding))

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:edit", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 403)


class ReviewEligibilityTests(TestCase):

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead_author = make_user(User.Role.TEAM_LEAD)
        self.senior_author = make_user(User.Role.SENIOR)
        self.consultant_author = make_user(User.Role.CONSULTANT)

    def test_team_lead_can_review_any_authors_finding(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        for author in (self.team_lead_author, self.senior_author, self.consultant_author):
            with self.subTest(author=author):
                finding = make_finding(self.engagement, author)
                self.assertTrue(review.is_eligible_reviewer(team_lead, finding))

    def test_senior_can_review_any_authors_finding(self):
        senior = make_user(User.Role.SENIOR)
        for author in (self.team_lead_author, self.senior_author, self.consultant_author):
            with self.subTest(author=author):
                finding = make_finding(self.engagement, author)
                self.assertTrue(review.is_eligible_reviewer(senior, finding))

    def test_consultant_never_eligible_to_review_or_qa(self):
        finding = make_finding(self.engagement, self.consultant_author)
        other_consultant = make_user(User.Role.CONSULTANT)
        self.assertFalse(review.is_eligible_reviewer(other_consultant, finding))
        self.assertFalse(review.is_eligible_qa_reviewer(other_consultant, finding))

    def test_senior_cannot_review_or_qa_own_finding(self):
        finding = make_finding(self.engagement, self.senior_author)
        self.assertFalse(review.is_eligible_reviewer(self.senior_author, finding))
        self.assertFalse(review.is_eligible_qa_reviewer(self.senior_author, finding))
        self.assertNotIn(self.senior_author, review.eligible_reviewer_candidates(finding))
        self.assertNotIn(self.senior_author, review.eligible_qa_candidates(finding))

    def test_team_lead_can_review_and_qa_own_finding(self):
        finding = make_finding(self.engagement, self.team_lead_author)
        self.assertTrue(review.is_eligible_reviewer(self.team_lead_author, finding))
        self.assertTrue(review.is_eligible_qa_reviewer(self.team_lead_author, finding))
        self.assertIn(self.team_lead_author, review.eligible_reviewer_candidates(finding))
        self.assertIn(self.team_lead_author, review.eligible_qa_candidates(finding))

    def test_team_lead_and_senior_can_review_superadmin_authored_finding(self):
        superadmin_author = make_user(User.Role.SUPERADMIN)
        finding = make_finding(self.engagement, superadmin_author)
        team_lead = make_user(User.Role.TEAM_LEAD)
        senior = make_user(User.Role.SENIOR)
        self.assertTrue(review.is_eligible_reviewer(team_lead, finding))
        self.assertTrue(review.is_eligible_reviewer(senior, finding))
        self.assertIn(team_lead, review.eligible_reviewer_candidates(finding))
        self.assertIn(senior, review.eligible_reviewer_candidates(finding))

    def test_role_without_review_permission_is_never_eligible(self):
        limited_role = Role.objects.create(name="Catalogue Curator")
        limited_role.permissions.set(Permission.objects.filter(codename="catalogue.manage"))
        limited_user = make_user(User.Role.CONSULTANT)
        limited_user.role = limited_role
        limited_user.save(update_fields=["role"])

        finding = make_finding(self.engagement, self.consultant_author)
        self.assertFalse(review.is_eligible_reviewer(limited_user, finding))
        self.assertFalse(review.is_eligible_qa_reviewer(limited_user, finding))

    def test_custom_role_with_review_permission_is_eligible(self):
        custom_role = Role.objects.create(name="Peer Reviewer")
        custom_role.permissions.set(
            Permission.objects.filter(codename__in=["findings.review", "findings.qa"])
        )
        custom_user = make_user(User.Role.CONSULTANT)
        custom_user.role = custom_role
        custom_user.save(update_fields=["role"])

        finding = make_finding(self.engagement, self.team_lead_author)
        self.assertTrue(review.is_eligible_reviewer(custom_user, finding))
        self.assertTrue(review.is_eligible_qa_reviewer(custom_user, finding))


class AssignReviewerTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author)

    def test_team_lead_can_assign_eligible_reviewer(self):
        senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, senior)

    def test_assignment_grants_engagement_membership(self):
        senior = make_user(User.Role.SENIOR)
        self.assertFalse(EngagementMembership.objects.filter(user=senior, engagement=self.engagement).exists())
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        membership = EngagementMembership.objects.get(user=senior, engagement=self.engagement)
        self.assertEqual(membership.added_by, self.team_lead)

    def test_author_can_assign_reviewer_to_own_finding(self):
        senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=senior, engagement=self.engagement)
        review.assign_reviewer(self.finding, senior, assigned_by=self.consultant_author)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, senior)

    def test_author_cannot_assign_reviewer_to_non_member(self):
        senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.assign_reviewer(self.finding, senior, assigned_by=self.consultant_author)

    def test_non_manager_non_author_cannot_assign(self):
        senior = make_user(User.Role.SENIOR)
        bystander = make_user(User.Role.CONSULTANT)
        with self.assertRaises(PermissionDenied):
            review.assign_reviewer(self.finding, senior, assigned_by=bystander)

    def test_ineligible_candidate_rejected(self):
        other_consultant = make_user(User.Role.CONSULTANT)
        with self.assertRaises(PermissionDenied):
            review.assign_reviewer(self.finding, other_consultant, assigned_by=self.team_lead)

    def test_cannot_assign_once_reviewed(self):
        senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        review.submit_review(self.finding, senior, Finding.WorkflowStatus.REVIEWED)
        another_senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.assign_reviewer(self.finding, another_senior, assigned_by=self.team_lead)


class SubmitReviewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author)
        self.senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, self.senior, assigned_by=self.team_lead)

    def test_assigned_reviewer_can_submit(self):
        review.submit_review(self.finding, self.senior, Finding.WorkflowStatus.REVIEWED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEWED)

    def test_non_assigned_user_cannot_submit(self):
        other_senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.submit_review(self.finding, other_senior, Finding.WorkflowStatus.REVIEWED)

    def test_superadmin_bypass(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        review.submit_review(self.finding, superadmin, Finding.WorkflowStatus.REVIEWED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEWED)

    def test_act_any_assignment_permission_bypasses_too(self):
        from apps.accounts.models import Permission, Role

        role = Role.objects.create(name=f"Custom {os.urandom(4).hex()}")
        role.slug = Role.unique_slug_from_name(role.name)
        role.save()
        role.permissions.add(Permission.objects.get(codename="findings.act_any_assignment"))
        overrider = User.objects.create(
            username=f"overrider-{os.urandom(4).hex()}", role=role, auth_type=User.AuthType.LOCAL,
        )
        review.submit_review(self.finding, overrider, Finding.WorkflowStatus.REVIEWED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEWED)

    def test_invalid_outcome_rejected(self):
        with self.assertRaises(ValueError):
            review.submit_review(self.finding, self.senior, "NOT_A_REAL_STATUS")

    def test_changes_requested_allows_resubmission(self):
        review.submit_review(self.finding, self.senior, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED)
        review.submit_review(self.finding, self.senior, Finding.WorkflowStatus.REVIEWED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEWED)


class AssignAndSubmitQATests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author)
        self.senior_reviewer = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, self.senior_reviewer, assigned_by=self.team_lead)
        review.submit_review(self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)

    def test_assign_qa_to_different_eligible_user(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, other_senior, assigned_by=self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, other_senior)

    def test_same_person_can_be_reviewer_and_qa(self):
        review.assign_qa(self.finding, self.senior_reviewer, assigned_by=self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, self.senior_reviewer)

    def test_cannot_assign_qa_before_reviewed(self):
        fresh_finding = make_finding(self.engagement, self.consultant_author)
        senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.assign_qa(fresh_finding, senior, assigned_by=self.team_lead)

    def test_qa_approve_full_happy_path(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, other_senior, assigned_by=self.team_lead)
        review.submit_qa(self.finding, other_senior, Finding.WorkflowStatus.QA_APPROVED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.QA_APPROVED)

    def test_non_assigned_qa_cannot_submit(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, other_senior, assigned_by=self.team_lead)
        yet_another_senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.submit_qa(self.finding, yet_another_senior, Finding.WorkflowStatus.QA_APPROVED)

    def test_assigned_reviewer_can_assign_qa(self):
        other_senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=other_senior, engagement=self.engagement)
        review.assign_qa(self.finding, other_senior, assigned_by=self.senior_reviewer)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, other_senior)

    def test_non_manager_non_reviewer_cannot_assign_qa(self):
        bystander = make_user(User.Role.SENIOR)
        other_senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.assign_qa(self.finding, other_senior, assigned_by=bystander)

    def test_author_can_assign_qa(self):
        other_senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=other_senior, engagement=self.engagement)
        review.assign_qa(self.finding, other_senior, assigned_by=self.consultant_author)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, other_senior)

    def test_author_cannot_assign_qa_to_non_member(self):
        other_senior = make_user(User.Role.SENIOR)
        with self.assertRaises(PermissionDenied):
            review.assign_qa(self.finding, other_senior, assigned_by=self.consultant_author)

    def test_qa_candidates_scoped_to_engagement_members_for_non_manager_assigner(self):
        member_senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=member_senior, engagement=self.engagement)
        outsider_senior = make_user(User.Role.SENIOR)

        candidates = review.eligible_qa_candidates(self.finding, assigned_by=self.senior_reviewer)
        self.assertIn(member_senior, candidates)
        self.assertNotIn(outsider_senior, candidates)

        with self.assertRaises(PermissionDenied):
            review.assign_qa(self.finding, outsider_senior, assigned_by=self.senior_reviewer)
        review.assign_qa(self.finding, member_senior, assigned_by=self.senior_reviewer)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, member_senior)

    def test_qa_candidates_unscoped_for_manager_assigner(self):
        outsider_senior = make_user(User.Role.SENIOR)
        candidates = review.eligible_qa_candidates(self.finding, assigned_by=self.team_lead)
        self.assertIn(outsider_senior, candidates)
        review.assign_qa(self.finding, outsider_senior, assigned_by=self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, outsider_senior)


class BulkReviewQATests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.senior = make_user(User.Role.SENIOR)
        self.findings = [make_finding(self.engagement, self.consultant_author) for _ in range(3)]

    def test_bulk_assign_reviewer_assigns_every_draft_finding(self):
        assigned, skipped = review.bulk_assign_reviewer(self.engagement, self.senior, assigned_by=self.team_lead)
        self.assertEqual(len(assigned), 3)
        self.assertEqual(skipped, [])
        for finding in self.findings:
            finding.refresh_from_db()
            self.assertEqual(finding.assigned_reviewer, self.senior)

    def test_bulk_assign_reviewer_skips_ineligible_self_authored_finding(self):
        review.assign_reviewer(self.findings[0], self.senior, assigned_by=self.team_lead)
        review.submit_review(self.findings[0], self.senior, Finding.WorkflowStatus.REVIEWED)

        assigned, skipped = review.bulk_assign_reviewer(
            self.engagement, self.consultant_author, assigned_by=self.team_lead,
        )
        self.assertEqual(len(assigned), 0)
        self.assertEqual(len(skipped), 2)

    def test_bulk_assign_reviewer_denies_non_manager(self):
        with self.assertRaises(PermissionDenied):
            review.bulk_assign_reviewer(self.engagement, self.senior, assigned_by=self.consultant_author)

    def test_bulk_submit_review_approves_only_my_assigned_findings(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.findings[0], self.senior, assigned_by=self.team_lead)
        review.assign_reviewer(self.findings[1], self.senior, assigned_by=self.team_lead)
        review.assign_reviewer(self.findings[2], other_senior, assigned_by=self.team_lead)

        updated, skipped = review.bulk_submit_review(self.engagement, self.senior, Finding.WorkflowStatus.REVIEWED)
        self.assertEqual(len(updated), 2)
        self.findings[0].refresh_from_db()
        self.findings[1].refresh_from_db()
        self.findings[2].refresh_from_db()
        self.assertEqual(self.findings[0].workflow_status, Finding.WorkflowStatus.REVIEWED)
        self.assertEqual(self.findings[1].workflow_status, Finding.WorkflowStatus.REVIEWED)
        self.assertEqual(self.findings[2].workflow_status, Finding.WorkflowStatus.DRAFT)

    def test_bulk_submit_review_superadmin_covers_everyone(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        review.assign_reviewer(self.findings[0], self.senior, assigned_by=self.team_lead)
        other_senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.findings[1], other_senior, assigned_by=self.team_lead)

        updated, skipped = review.bulk_submit_review(self.engagement, superadmin, Finding.WorkflowStatus.REVIEWED)
        self.assertEqual(len(updated), 3)

    def test_bulk_assign_qa_and_bulk_submit_qa_full_cycle(self):
        for finding in self.findings:
            review.assign_reviewer(finding, self.senior, assigned_by=self.team_lead)
        review.bulk_submit_review(self.engagement, self.senior, Finding.WorkflowStatus.REVIEWED)

        qa_person = make_user(User.Role.SENIOR)
        assigned, skipped = review.bulk_assign_qa(self.engagement, qa_person, assigned_by=self.team_lead)
        self.assertEqual(len(assigned), 3)

        updated, skipped = review.bulk_submit_qa(self.engagement, qa_person, Finding.WorkflowStatus.QA_APPROVED)
        self.assertEqual(len(updated), 3)
        for finding in self.findings:
            finding.refresh_from_db()
            self.assertEqual(finding.workflow_status, Finding.WorkflowStatus.QA_APPROVED)


class RetestWorkflowTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant)

    def test_cannot_log_retest_outside_remediation_statuses(self):
        self.assertEqual(self.engagement.status, Engagement.Status.IN_PROGRESS)
        self.assertFalse(retest.can_log_retest_result(self.consultant, self.finding))
        with self.assertRaises(PermissionDenied):
            retest.log_retest_result(
                self.finding, status=Finding.RetestStatus.FIXED, notes_ciphertext=None, tested_by=self.consultant,
            )

    def test_can_log_retest_while_awaiting_remediation_test(self):
        self.engagement.status = Engagement.Status.AWAITING_REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])
        self.assertTrue(retest.can_log_retest_result(self.consultant, self.finding))

        record = retest.log_retest_result(
            self.finding, status=Finding.RetestStatus.FIXED, notes_ciphertext=None, tested_by=self.consultant,
        )
        self.assertEqual(record.status, Finding.RetestStatus.FIXED)
        self.assertEqual(record.tested_by, self.consultant)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.retest_status, Finding.RetestStatus.FIXED)

    def test_can_log_retest_while_in_remediation_test(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])
        self.assertTrue(retest.can_log_retest_result(self.consultant, self.finding))

    def test_history_accumulates_across_multiple_retests(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])

        retest.log_retest_result(
            self.finding, status=Finding.RetestStatus.NOT_FIXED, notes_ciphertext=None, tested_by=self.consultant,
        )
        retest.log_retest_result(
            self.finding, status=Finding.RetestStatus.FIXED, notes_ciphertext=None, tested_by=self.consultant,
        )

        self.assertEqual(self.finding.retest_records.count(), 2)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.retest_status, Finding.RetestStatus.FIXED)

    def test_archived_finding_cannot_be_retested(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])
        self.finding.archived = True
        self.finding.save(update_fields=["archived"])

        self.assertFalse(retest.can_log_retest_result(self.consultant, self.finding))
        with self.assertRaises(PermissionDenied):
            retest.log_retest_result(
                self.finding, status=Finding.RetestStatus.FIXED, notes_ciphertext=None, tested_by=self.consultant,
            )

    def test_invalid_status_rejected(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            retest.log_retest_result(
                self.finding, status="BOGUS", notes_ciphertext=None, tested_by=self.consultant,
            )
        with self.assertRaises(ValueError):
            retest.log_retest_result(
                self.finding, status=Finding.RetestStatus.NOT_RETESTED, notes_ciphertext=None,
                tested_by=self.consultant,
            )


class RetestViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant)
        self.outsider = make_user(User.Role.CONSULTANT)

    def _url(self):
        return reverse("findings:retest_create", args=[self.engagement.pk, self.finding.pk])

    def test_member_can_log_retest_result_during_remediation_test(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])

        client = Client()
        login(client, self.consultant)
        resp = client.post(self._url(), {"status": Finding.RetestStatus.FIXED, "notes": doc_json("Confirmed patched.")})
        self.assertEqual(resp.status_code, 302)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.retest_status, Finding.RetestStatus.FIXED)
        record = self.finding.retest_records.get()
        key = get_data_key(self.engagement)
        notes_plain = decrypt_bytes(
            bytes(record.notes_ciphertext), key, associated_data=record_aad("retestrecord", record.pk, "notes"),
        ).decode()
        self.assertIn("Confirmed patched.", notes_plain)

    def test_rejected_outside_remediation_statuses(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(self._url(), {"status": Finding.RetestStatus.FIXED, "notes": ""})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.finding.retest_records.count(), 0)

    def test_non_member_cannot_log_retest(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])

        client = Client()
        login(client, self.outsider)
        resp = client.post(self._url(), {"status": Finding.RetestStatus.FIXED, "notes": ""})
        self.assertEqual(resp.status_code, 403)

    def test_disabled_feature_flag_blocks_logging_but_preserves_existing_history(self):
        from apps.feature_flags.models import FeatureFlags

        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])

        client = Client()
        login(client, self.consultant)
        client.post(self._url(), {"status": Finding.RetestStatus.NOT_FIXED, "notes": ""})
        self.assertEqual(self.finding.retest_records.count(), 1)

        flags = FeatureFlags.get_solo()
        flags.retest_workflow = False
        flags.save()

        resp = client.post(self._url(), {"status": Finding.RetestStatus.FIXED, "notes": ""})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.finding.retest_records.count(), 1)

        detail_resp = client.get(reverse("findings:detail", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(len(detail_resp.context["retest_records"]), 1)
        self.assertFalse(detail_resp.context["can_log_retest"])

    def test_detail_page_explains_why_retest_is_unavailable_due_to_engagement_status(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:detail", args=[self.engagement.pk, self.finding.pk]))
        self.assertTrue(resp.context["retest_workflow_enabled"])
        self.assertFalse(resp.context["can_log_retest"])
        self.assertContains(resp, "Retest results can only be logged while the engagement is")

    def test_no_explanation_shown_once_engagement_is_in_a_retest_status(self):
        self.engagement.status = Engagement.Status.REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("findings:detail", args=[self.engagement.pk, self.finding.pk]))
        self.assertTrue(resp.context["can_log_retest"])
        self.assertNotContains(resp, "Retest results can only be logged while the engagement is")


class ReopenToDraftTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author)
        self.senior_reviewer = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, self.senior_reviewer, assigned_by=self.team_lead)
        review.submit_review(self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)

    def test_manager_can_reopen_reviewed_finding(self):
        review.reopen_to_draft(self.finding, self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)

    def test_reopen_clears_assignments(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, other_senior, assigned_by=self.team_lead)
        review.reopen_to_draft(self.finding, self.team_lead)
        self.finding.refresh_from_db()
        self.assertIsNone(self.finding.assigned_reviewer)
        self.assertIsNone(self.finding.assigned_qa)

    def test_manager_can_reopen_qa_approved_finding(self):
        other_senior = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, other_senior, assigned_by=self.team_lead)
        review.submit_qa(self.finding, other_senior, Finding.WorkflowStatus.QA_APPROVED)
        review.reopen_to_draft(self.finding, self.team_lead)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)

    def test_non_manager_cannot_reopen(self):
        with self.assertRaises(PermissionDenied):
            review.reopen_to_draft(self.finding, self.senior_reviewer)

    def test_cannot_reopen_already_draft_finding(self):
        fresh_finding = make_finding(self.engagement, self.consultant_author)
        with self.assertRaises(PermissionDenied):
            review.reopen_to_draft(fresh_finding, self.team_lead)

    def test_superadmin_can_reopen(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        review.reopen_to_draft(self.finding, superadmin)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)

    def test_reopened_finding_is_editable_again(self):
        review.reopen_to_draft(self.finding, self.team_lead)
        self.finding.refresh_from_db()
        self.assertTrue(can_edit_finding_content(self.consultant_author, self.finding))


class EditLockTests(TestCase):

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant)

    def _edit_form_data(self, **overrides):
        data = {
            "title": self.finding.title,
            "cvss_score": "6.1",
            "cvss_vector": "",
            "severity": Finding.Severity.MEDIUM,
            "classification_taxonomy": [self.tag.taxonomy],
            "classification_value": [self.tag.value],
            "cve_id": "",
            "status": Finding.Status.OPEN,
            "affects": "",
            section_post_key("vulnerability_description"): doc_json("Updated description."),
            section_post_key("business_impact"): doc_json(""),
            section_post_key("testing_summary"): doc_json(""),
            section_post_key("technical_details"): doc_json("Updated technical details."),
            section_post_key("note"): "",
            section_post_key("recommendations"): doc_json(""),
            section_post_key("references"): doc_json(""),
        }
        data.update(overrides)
        return data

    def test_draft_is_editable(self):
        self.assertTrue(can_edit_finding_content(self.consultant, self.finding))

    def test_reviewed_finding_is_still_editable(self):
        self.finding.workflow_status = Finding.WorkflowStatus.REVIEWED
        self.finding.save()
        self.assertTrue(can_edit_finding_content(self.consultant, self.finding))

    def test_editing_reviewed_finding_reopens_to_draft_and_keeps_assignment(self):
        senior = make_user(User.Role.SENIOR)
        self.finding.workflow_status = Finding.WorkflowStatus.REVIEWED
        self.finding.assigned_reviewer = senior
        self.finding.save()

        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, self.finding.pk]),
            self._edit_form_data(title="Reflected XSS (updated)"),
        )
        self.assertEqual(resp.status_code, 302)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.title, "Reflected XSS (updated)")
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)
        self.assertEqual(self.finding.assigned_reviewer, senior)

    def test_editing_qa_approved_finding_reopens_to_reviewed_and_keeps_assignments(self):
        senior = make_user(User.Role.SENIOR)
        self.finding.workflow_status = Finding.WorkflowStatus.QA_APPROVED
        self.finding.assigned_reviewer = senior
        self.finding.assigned_qa = senior
        self.finding.save()

        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, self.finding.pk]),
            self._edit_form_data(),
        )
        self.assertEqual(resp.status_code, 302)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.REVIEWED)
        self.assertEqual(self.finding.assigned_reviewer, senior)
        self.assertEqual(self.finding.assigned_qa, senior)

    def test_editing_draft_finding_does_not_touch_workflow_status(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, self.finding.pk]),
            self._edit_form_data(),
        )
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)

    def test_editing_unassigned_draft_auto_assigns_when_engagement_in_review(self):
        reviewer = make_user(User.Role.SENIOR)
        self.engagement.default_reviewer = reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:edit", args=[self.engagement.pk, self.finding.pk]),
            self._edit_form_data(),
        )
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, reviewer)


class ReviewHttpFlowTests(TestCase):

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant)
        self.senior = make_user(User.Role.SENIOR)
        self.qa_senior = make_user(User.Role.SENIOR)

    def test_full_review_qa_cycle_via_http(self):
        tl_client = Client()
        login(tl_client, self.team_lead)

        resp = tl_client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": self.senior.pk},
        )
        self.assertEqual(resp.status_code, 302)

        senior_client = Client()
        login(senior_client, self.senior)

        queue_resp = senior_client.get(reverse("queue:my_queue"))
        self.assertContains(queue_resp, self.finding.title)

        resp = senior_client.post(
            reverse("findings:submit_review", args=[self.engagement.pk, self.finding.pk]),
            {"outcome": "REVIEWED"},
        )
        self.assertEqual(resp.status_code, 302)

        resp = tl_client.post(
            reverse("findings:assign_qa", args=[self.engagement.pk, self.finding.pk]),
            {"qa_reviewer": self.qa_senior.pk},
        )
        self.assertEqual(resp.status_code, 302)

        qa_client = Client()
        login(qa_client, self.qa_senior)
        qa_queue_resp = qa_client.get(reverse("queue:my_queue"))
        self.assertContains(qa_queue_resp, self.finding.title)

        resp = qa_client.post(
            reverse("findings:submit_qa", args=[self.engagement.pk, self.finding.pk]),
            {"outcome": "QA_APPROVED"},
        )
        self.assertEqual(resp.status_code, 302)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.QA_APPROVED)
        self.assertNotEqual(self.finding.assigned_reviewer_id, self.finding.assigned_qa_id)

        resp = tl_client.post(reverse("findings:reopen_to_draft", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.workflow_status, Finding.WorkflowStatus.DRAFT)
        self.assertIsNone(self.finding.assigned_reviewer)
        self.assertIsNone(self.finding.assigned_qa)

    def test_consultant_cannot_reopen_via_http(self):
        client = Client()
        login(client, self.consultant)
        self.finding.workflow_status = Finding.WorkflowStatus.QA_APPROVED
        self.finding.save()
        resp = client.post(reverse("findings:reopen_to_draft", args=[self.engagement.pk, self.finding.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_author_can_assign_reviewer_to_own_finding_via_http(self):
        EngagementMembership.objects.create(user=self.senior, engagement=self.engagement)
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": self.senior.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, self.senior)

    def test_non_author_consultant_cannot_assign_reviewer_via_http(self):
        EngagementMembership.objects.create(user=self.senior, engagement=self.engagement)
        bystander = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=bystander, engagement=self.engagement)
        client = Client()
        login(client, bystander)
        resp = client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": self.senior.pk},
        )
        self.assertEqual(resp.status_code, 403)

    def test_invalid_outcome_is_not_reflected_in_response(self):
        tl_client = Client()
        login(tl_client, self.team_lead)
        tl_client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": self.senior.pk},
        )

        senior_client = Client()
        login(senior_client, self.senior)
        payload = "REVIEW_CHANGES_REQUESTED<script>alert(1)</script>"
        resp = senior_client.post(
            reverse("findings:submit_review", args=[self.engagement.pk, self.finding.pk]),
            {"outcome": payload},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn(b"<script>alert(1)</script>", resp.content)
        self.assertNotIn(payload.encode(), resp.content)


class AssignReviewerQAViewEnumerationTests(TestCase):

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant)
        self.tl_client = Client()
        login(self.tl_client, self.team_lead)

    def test_nonexistent_and_ineligible_reviewer_pk_both_404(self):
        ineligible = make_user(User.Role.CONSULTANT)
        nonexistent_pk = "999999999"

        resp_ineligible = self.tl_client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": ineligible.pk},
        )
        resp_nonexistent = self.tl_client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": nonexistent_pk},
        )
        self.assertEqual(resp_ineligible.status_code, 404)
        self.assertEqual(resp_nonexistent.status_code, 404)

    def test_eligible_reviewer_still_assignable(self):
        senior = make_user(User.Role.SENIOR)
        resp = self.tl_client.post(
            reverse("findings:assign_reviewer", args=[self.engagement.pk, self.finding.pk]),
            {"reviewer": senior.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, senior)

    def test_nonexistent_and_ineligible_qa_pk_both_404(self):
        senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        review.submit_review(self.finding, senior, Finding.WorkflowStatus.REVIEWED)

        ineligible = make_user(User.Role.CONSULTANT)
        nonexistent_pk = "999999999"

        resp_ineligible = self.tl_client.post(
            reverse("findings:assign_qa", args=[self.engagement.pk, self.finding.pk]),
            {"qa_reviewer": ineligible.pk},
        )
        resp_nonexistent = self.tl_client.post(
            reverse("findings:assign_qa", args=[self.engagement.pk, self.finding.pk]),
            {"qa_reviewer": nonexistent_pk},
        )
        self.assertEqual(resp_ineligible.status_code, 404)
        self.assertEqual(resp_nonexistent.status_code, 404)


class RecurrenceTests(TestCase):
    def setUp(self):
        tags = list(ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021")[:2])
        self.tag_a, self.tag_b = tags[0], tags[1]

        self.author = make_user(User.Role.CONSULTANT)

        self.acme_1 = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.acme_1)
        self.acme_2 = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.acme_2)
        self.globex = Engagement.objects.create(client_name="Globex")
        generate_project_key(self.globex)

        self.finding = make_finding(self.acme_1, self.author, title="SQL Injection")
        self.finding.classifications.set([self.tag_a])

    def test_similar_catalogue_entries_matches_on_shared_tag(self):
        matching_template = VulnerabilityTemplate.objects.create(
            title="Generic SQLi", default_severity=Finding.Severity.HIGH, created_by=self.author,
        )
        matching_template.classifications.set([self.tag_a])
        non_matching_template = VulnerabilityTemplate.objects.create(
            title="Unrelated", default_severity=Finding.Severity.LOW, created_by=self.author,
        )
        non_matching_template.classifications.set([self.tag_b])

        results = recurrence.similar_catalogue_entries(self.finding)
        self.assertEqual(results, [matching_template])

    def test_repeat_findings_for_client_matches_across_engagements_same_client(self):
        repeat = make_finding(self.acme_2, self.author, title="SQL Injection again")
        repeat.classifications.set([self.tag_a])
        unrelated = make_finding(self.acme_2, self.author, title="Unrelated finding")
        unrelated.classifications.set([self.tag_b])
        other_client = make_finding(self.globex, self.author, title="SQL Injection elsewhere")
        other_client.classifications.set([self.tag_a])

        results = recurrence.repeat_findings_for_client(self.finding)
        self.assertEqual(results, [repeat])

    def test_finding_with_no_classifications_has_no_matches(self):
        bare = make_finding(self.acme_1, self.author, title="Untagged")
        bare.classifications.clear()
        self.assertEqual(recurrence.similar_catalogue_entries(bare), [])
        self.assertEqual(recurrence.repeat_findings_for_client(bare), [])

    def test_excludes_itself_from_repeat_findings(self):
        self.assertNotIn(self.finding, recurrence.repeat_findings_for_client(self.finding))

    def test_disabled_feature_flag_hides_recurrence_panel_on_finding_detail(self):
        from apps.feature_flags.models import FeatureFlags

        repeat = make_finding(self.acme_2, self.author, title="SQL Injection again")
        repeat.classifications.set([self.tag_a])
        EngagementMembership.objects.create(user=self.author, engagement=self.acme_1)

        client = Client()
        login(client, self.author)
        url = reverse("findings:detail", args=[self.acme_1.pk, self.finding.pk])

        resp = client.get(url)
        self.assertEqual(resp.context["repeat_findings_for_client"], [repeat])

        flags = FeatureFlags.get_solo()
        flags.recurrence_and_trends = False
        flags.save()

        resp = client.get(url)
        self.assertEqual(resp.context["repeat_findings_for_client"], [])
        self.assertEqual(resp.context["similar_catalogue_entries"], [])


NMAP_SAMPLE = b"""<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -oX out.xml -sV --script vuln 10.0.0.5">
<host><status state="up"/>
<address addr="10.0.0.5" addrtype="ipv4"/>
<hostnames><hostname name="web01.internal" type="PTR"/></hostnames>
<ports>
<port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="8.9p1"/></port>
<port protocol="tcp" portid="443"><state state="open"/><service name="https" product="nginx" version="1.18.0"/>
<script id="http-vuln-cve2021-44228" output="VULNERABLE:&#10;Log4Shell&#10;  State: VULNERABLE&#10;  IDs: CVE-2021-44228&#10;  Risk factor: High"/>
</port>
<port protocol="tcp" portid="8080"><state state="closed"/><service name="http-proxy"/></port>
</ports>
</host>
</nmaprun>
"""

BURP_SAMPLE = b"""<?xml version="1.0"?>
<issues burpVersion="2023.1" exportTime="Mon Jan 01 00:00:00 UTC 2026">
<issue>
<serialNumber>1</serialNumber>
<name>Cross-site scripting (reflected)</name>
<host ip="10.0.0.5">https://app.acme.com</host>
<path>/search?q=test</path>
<severity>High</severity>
<confidence>Certain</confidence>
<issueBackground isBase64="true">PHA+VGhpcyBpcyBhIHJlZmxlY3RlZCBYU1MgaXNzdWUuPC9wPg==</issueBackground>
<remediationBackground isBase64="true">PHA+RW5jb2RlIG91dHB1dCBjb250ZXh0dWFsbHkuPC9wPg==</remediationBackground>
</issue>
<issue>
<serialNumber>2</serialNumber>
<name>Strict-Transport-Security not enforced</name>
<host ip="10.0.0.5">https://app.acme.com</host>
<path>/</path>
<severity>Information</severity>
<confidence>Firm</confidence>
<issueBackground>&lt;p&gt;HSTS not set.&lt;/p&gt;</issueBackground>
</issue>
</issues>
"""

NUCLEI_SAMPLE = (
    b'{"template-id":"exposed-panels/wp-admin","info":{"name":"Wordpress Admin Panel",'
    b'"severity":"info","description":"WordPress admin panel exposed.","tags":"panel,wordpress"},'
    b'"host":"https://app.acme.com","matched-at":"https://app.acme.com/wp-admin/"}\n'
    b'{"template-id":"CVE-2021-44228","info":{"name":"Apache Log4j RCE","severity":"critical",'
    b'"description":"Log4Shell remote code execution.","tags":["cve","rce","log4j"],'
    b'"classification":{"cve-id":["CVE-2021-44228"]}},"host":"https://app.acme.com",'
    b'"matched-at":"https://app.acme.com/api/login"}\n'
)


class ScanImporterParserTests(TestCase):

    def test_nmap_open_ports_and_vuln_script(self):
        from .importers import nmap

        results = nmap.parse(NMAP_SAMPLE)
        self.assertEqual(len(results), 2)

        ssh = next(r for r in results if "22/tcp" in r.title)
        self.assertEqual(ssh.severity, "INFORMATIONAL")
        self.assertIn("OpenSSH 8.9p1", ssh.technical_details)

        vuln = next(r for r in results if "443/tcp" in r.title)
        self.assertEqual(vuln.severity, "HIGH")
        self.assertEqual(vuln.cve_id, "CVE-2021-44228")

    def test_nmap_closed_ports_excluded(self):
        from .importers import nmap

        results = nmap.parse(NMAP_SAMPLE)
        self.assertFalse(any("8080" in r.title for r in results))

    def test_nmap_rejects_non_nmap_xml(self):
        from .importers import nmap

        with self.assertRaises(ValueError):
            nmap.parse(b"<not-nmap/>")

    def test_nmap_rejects_entity_expansion_attack(self):
        from .importers import nmap

        payload = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE nmaprun ['
            b'<!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
            b']>'
            b'<nmaprun>&c;</nmaprun>'
        )
        with self.assertRaises(ValueError):
            nmap.parse(payload)

    def test_burp_severity_mapping_and_base64_decode(self):
        from .importers import burp

        results = burp.parse(BURP_SAMPLE)
        self.assertEqual(len(results), 2)

        xss = results[0]
        self.assertEqual(xss.severity, "HIGH")
        self.assertIn("This is a reflected XSS issue.", xss.technical_details)
        self.assertIn("Encode output contextually.", xss.technical_details)
        self.assertNotIn("<p>", xss.technical_details)

        info = results[1]
        self.assertEqual(info.severity, "INFORMATIONAL")
        self.assertIn("HSTS not set.", info.technical_details)

    def test_burp_entity_encoded_tag_is_stripped_not_revived(self):
        from .importers import burp

        sample = b"""<?xml version="1.0"?>
<issues burpVersion="2023.1" exportTime="Mon Jan 01 00:00:00 UTC 2026">
<issue>
<serialNumber>1</serialNumber>
<name>Reflected input</name>
<host ip="10.0.0.5">https://app.acme.com</host>
<path>/search</path>
<severity>Medium</severity>
<confidence>Firm</confidence>
<issueBackground>The app reflected &lt;script&gt;alert(document.cookie)&lt;/script&gt; back.</issueBackground>
</issue>
</issues>
"""
        results = burp.parse(sample)
        self.assertEqual(len(results), 1)
        self.assertNotIn("<script>", results[0].technical_details)
        self.assertNotIn("</script>", results[0].technical_details)

    def test_burp_rejects_non_burp_xml(self):
        from .importers import burp

        with self.assertRaises(ValueError):
            burp.parse(b"<not-burp/>")

    def test_nuclei_severity_and_cve_and_tags(self):
        from .importers import nuclei

        results = nuclei.parse(NUCLEI_SAMPLE)
        self.assertEqual(len(results), 2)

        info_result = results[0]
        self.assertEqual(info_result.severity, "INFORMATIONAL")
        self.assertEqual(info_result.tags, ["panel", "wordpress"])

        critical = results[1]
        self.assertEqual(critical.severity, "CRITICAL")
        self.assertEqual(critical.cve_id, "CVE-2021-44228")
        self.assertEqual(critical.tags, ["cve", "rce", "log4j"])

    def test_nuclei_rejects_invalid_json_line(self):
        from .importers import nuclei

        with self.assertRaises(ValueError):
            nuclei.parse(b"not json\n")

    def test_nuclei_rejects_deeply_nested_json_line_gracefully(self):
        from .importers import nuclei

        deeply_nested = b"[" * 100000 + b"\n"
        with self.assertRaises(ValueError):
            nuclei.parse(deeply_nested)

    def test_nuclei_rejects_empty_input(self):
        from .importers import nuclei

        with self.assertRaises(ValueError):
            nuclei.parse(b"")


class ScanImportViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.outsider = make_user(User.Role.CONSULTANT)

    def _url(self):
        return reverse("findings:import", args=[self.engagement.pk])

    def test_member_can_import_nmap_results(self):
        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.xml", NMAP_SAMPLE, content_type="text/xml")
        resp = client.post(self._url(), {"format": "NMAP", "file": upload})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 2)
        self.assertTrue(
            Finding.objects.filter(engagement=self.engagement, workflow_status=Finding.WorkflowStatus.DRAFT).exists()
        )

    def test_import_creates_scan_import_record(self):
        from .models import ScanImportRecord

        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.xml", NMAP_SAMPLE, content_type="text/xml")
        client.post(self._url(), {"format": "NMAP", "file": upload})

        record = ScanImportRecord.objects.get(engagement=self.engagement)
        self.assertEqual(record.source_format, "NMAP")
        self.assertEqual(record.filename, "scan.xml")
        self.assertEqual(record.findings_created, 2)
        self.assertEqual(record.imported_by, self.consultant)

    def test_oversized_file_rejected_without_importing(self):
        from .forms import MAX_IMPORT_FILE_SIZE

        client = Client()
        login(client, self.consultant)
        oversized = SimpleUploadedFile("scan.xml", b"x" * (MAX_IMPORT_FILE_SIZE + 1), content_type="text/xml")
        resp = client.post(self._url(), {"format": "NMAP", "file": oversized})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 0)
        for finding in Finding.objects.filter(engagement=self.engagement):
            self.assertGreater(finding.classifications.count(), 0)
            for tag in finding.classifications.all():
                self.assertEqual(tag.taxonomy, "Nmap")

    def test_member_can_import_burp_results(self):
        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.xml", BURP_SAMPLE, content_type="text/xml")
        resp = client.post(self._url(), {"format": "BURP", "file": upload})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 2)
        xss = Finding.objects.get(engagement=self.engagement, severity=Finding.Severity.HIGH)
        key = get_data_key(self.engagement)
        plaintext = decrypt_finding_section(xss, "technical-details", key)
        self.assertIn("reflected XSS", plaintext)
        for finding in Finding.objects.filter(engagement=self.engagement):
            self.assertGreater(finding.classifications.count(), 0)
            for tag in finding.classifications.all():
                self.assertEqual(tag.taxonomy, "Burp Suite")

    def test_member_can_import_nuclei_results_with_tags(self):
        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.jsonl", NUCLEI_SAMPLE, content_type="application/json")
        resp = client.post(self._url(), {"format": "NUCLEI", "file": upload})
        self.assertEqual(resp.status_code, 302)

        critical = Finding.objects.get(engagement=self.engagement, severity=Finding.Severity.CRITICAL)
        self.assertEqual(critical.cve_id, "CVE-2021-44228")
        self.assertEqual(
            set(critical.classifications.values_list("taxonomy", "value")),
            {("Nuclei", "cve"), ("Nuclei", "rce"), ("Nuclei", "log4j")},
        )

    def test_non_member_cannot_import(self):
        client = Client()
        login(client, self.outsider)
        upload = SimpleUploadedFile("scan.xml", NMAP_SAMPLE, content_type="text/xml")
        resp = client.post(self._url(), {"format": "NMAP", "file": upload})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 0)

    def test_invalid_file_shows_form_error_not_crash(self):
        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.xml", b"<garbage/>", content_type="text/xml")
        resp = client.post(self._url(), {"format": "NMAP", "file": upload})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Not an Nmap XML report")

    def test_disabled_feature_flag_blocks_import(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.scan_import = False
        flags.save()

        client = Client()
        login(client, self.consultant)
        upload = SimpleUploadedFile("scan.xml", NMAP_SAMPLE, content_type="text/xml")
        resp = client.post(self._url(), {"format": "NMAP", "file": upload})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 0)
        self.assertEqual(Finding.objects.filter(engagement=self.engagement).count(), 0)


class DisplayIdAssignmentTests(TestCase):

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.author = make_user(User.Role.CONSULTANT)

    def test_numbers_sequentially_in_the_order_given(self):
        from .display_id import assign_display_ids

        critical = make_finding(self.engagement, self.author, title="A critical one", severity=Finding.Severity.CRITICAL)
        medium = make_finding(self.engagement, self.author, title="A medium one", severity=Finding.Severity.MEDIUM)
        low = make_finding(self.engagement, self.author, title="A low one", severity=Finding.Severity.LOW)

        assign_display_ids([critical, medium, low])

        self.assertEqual(critical.display_id, "F001")
        self.assertEqual(medium.display_id, "F002")
        self.assertEqual(low.display_id, "F003")

    def test_renumbers_completely_on_every_call_not_stable(self):
        from .display_id import assign_display_ids

        a = make_finding(self.engagement, self.author, title="A", severity=Finding.Severity.LOW)
        b = make_finding(self.engagement, self.author, title="B", severity=Finding.Severity.CRITICAL)

        assign_display_ids([a, b])
        self.assertEqual((a.display_id, b.display_id), ("F001", "F002"))

        assign_display_ids([b, a])
        self.assertEqual((b.display_id, a.display_id), ("F001", "F002"))

    def test_not_persisted_to_the_database(self):
        from .display_id import assign_display_ids

        finding = make_finding(self.engagement, self.author, title="Ephemeral", severity=Finding.Severity.HIGH)
        assign_display_ids([finding])
        self.assertEqual(finding.display_id, "F001")

        finding.refresh_from_db()
        self.assertEqual(finding.display_id, "")

