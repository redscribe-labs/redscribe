import csv
import io
import json
import os

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.crypto.services import decrypt_bytes, encrypt_bytes, generate_project_key, get_data_key, record_aad
from apps.engagements.models import Engagement, EngagementMembership

from . import importer
from .models import ChecklistItem, ChecklistItemComment, ChecklistTemplate, ChecklistTemplateItem
from .services import instantiate_checklist

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"


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


def doc_json(text: str) -> str:
    return json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]})


def make_default_template(name="Default Template"):
    template = ChecklistTemplate.objects.create(name=name, is_default=True)
    ChecklistTemplateItem.objects.bulk_create([
        ChecklistTemplateItem(
            template=template, category="Information Gathering", code="TEST-01", title="Test item one", order=0,
        ),
        ChecklistTemplateItem(
            template=template, category="Information Gathering", code="TEST-02", title="Test item two", order=1,
        ),
    ])
    return template


class ImporterTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def test_json_import_creates_template_and_items(self):
        rows = [
            {"category": "Cat A", "code": "A-01", "title": "Do the thing", "reference_info": "Some guidance"},
            {"category": "Cat A", "code": "A-02", "title": "Do another thing"},
        ]
        count = importer.import_json("Custom List", "desc", json.dumps(rows), uploaded_by=self.superadmin)
        self.assertEqual(count, 2)
        template = ChecklistTemplate.objects.get(name="Custom List")
        self.assertEqual(template.items.count(), 2)
        item = template.items.get(code="A-01")
        self.assertEqual(json.loads(item.reference_info)["content"][0]["content"][0]["text"], "Some guidance")

    def test_import_strips_unsafe_link_protocols_but_keeps_safe_ones(self):
        def linked(href):
            return json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": href}}]},
            ]}]})
        rows = [
            {"category": "C", "title": "Bad", "reference_info": linked("javascript:alert(1)")},
            {"category": "C", "title": "Good", "reference_info": linked("https://owasp.org/")},
        ]
        importer.import_json("Links", "", json.dumps(rows), uploaded_by=self.superadmin)
        bad, good = ChecklistTemplateItem.objects.filter(template__name="Links").order_by("order")
        self.assertNotIn("javascript", bad.reference_info)
        self.assertIn("https://owasp.org/", good.reference_info)

    def test_reference_accepts_nested_doc_object(self):
        doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Nested"}]}]}
        rows = [{"category": "C", "title": "T", "reference_info": doc}]
        importer.import_json("Nested", "", json.dumps(rows), uploaded_by=self.superadmin)
        item = ChecklistTemplateItem.objects.get(template__name="Nested")
        self.assertEqual(json.loads(item.reference_info), doc)

    def test_bad_rows_report_the_row_instead_of_crashing(self):
        cases = [
            ([{"category": "C", "title": "T", "reference_info": {"type": "paragraph"}}], "Row 1"),
            ([{"category": "C", "title": "T", "reference_info": 5}], "Row 1"),
            ([{"category": "C", "title": "T"}, "not an object"], "Row 2"),
        ]
        for rows, expected in cases:
            with self.assertRaisesMessage(ValueError, expected):
                importer.import_json("Bad", "", json.dumps(rows), uploaded_by=self.superadmin)
        self.assertFalse(ChecklistTemplate.objects.filter(name="Bad").exists())

    def test_overly_nested_reference_is_rejected_with_its_row(self):
        node = {"type": "paragraph"}
        for _ in range(200):
            node = {"type": "blockquote", "content": [node]}
        rows = [{"category": "C", "title": "T"}, {"category": "C", "title": "T2", "reference_info": {"type": "doc", "content": [node]}}]
        with self.assertRaisesMessage(ValueError, "Row 2"):
            importer.import_json("Deep", "", json.dumps(rows), uploaded_by=self.superadmin)

    def test_envelope_validation(self):
        for payload, expected in [
            ({"format": "something-else", "items": []}, "Unrecognised"),
            ({"version": 99, "items": []}, "version 99"),
            ({"version": 1}, "'items' list"),
            ({"name": "N"}, "'items' list"),
        ]:
            with self.assertRaisesMessage(ValueError, expected):
                importer.import_json("X", "", json.dumps(payload), uploaded_by=self.superadmin)
        with self.assertRaisesMessage(ValueError, "name"):
            importer.import_json("", "", json.dumps({"items": []}), uploaded_by=self.superadmin)

    def test_json_import_missing_title_rejected(self):
        rows = [{"category": "Cat A"}]
        with self.assertRaises(ValueError):
            importer.import_json("Bad List", "", json.dumps(rows), uploaded_by=self.superadmin)
        self.assertFalse(ChecklistTemplate.objects.filter(name="Bad List").exists())

    def test_deeply_nested_json_rejected_gracefully(self):
        with self.assertRaises(ValueError):
            importer.import_json("Bad List", "", "[" * 100000, uploaded_by=self.superadmin)
        self.assertFalse(ChecklistTemplate.objects.filter(name="Bad List").exists())

    def test_reupload_replaces_items_without_touching_instantiated_checklist(self):
        importer.import_json(
            "Reupload Test", "",
            json.dumps([{"category": "Cat A", "code": "A-01", "title": "Original title"}]),
            uploaded_by=self.superadmin,
        )
        template = ChecklistTemplate.objects.get(name="Reupload Test")

        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        instantiate_checklist(engagement, template=template)
        instance_item = ChecklistItem.objects.get(run__engagement=engagement)
        self.assertEqual(instance_item.title, "Original title")

        importer.import_json(
            "Reupload Test", "",
            json.dumps([{"category": "Cat A", "code": "A-01", "title": "Replaced title"}]),
            uploaded_by=self.superadmin,
        )
        template.refresh_from_db()
        self.assertEqual(template.items.get(code="A-01").title, "Replaced title")

        instance_item.refresh_from_db()
        self.assertEqual(instance_item.title, "Original title")

    def test_csv_import(self):
        csv_text = "category,code,title,reference_info\nCat B,B-01,Test the thing,Guidance here\n"
        count = importer.import_csv("CSV List", "", csv_text, uploaded_by=self.superadmin)
        self.assertEqual(count, 1)
        item = ChecklistTemplate.objects.get(name="CSV List").items.first()
        self.assertEqual(item.title, "Test the thing")

    def test_csv_missing_columns_rejected(self):
        with self.assertRaises(ValueError):
            importer.import_csv("Bad CSV", "", "foo,bar\n1,2\n", uploaded_by=self.superadmin)


class InstantiateChecklistTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        make_default_template()

    def test_instantiates_from_default_template(self):
        run = instantiate_checklist(self.engagement)
        count = ChecklistItem.objects.filter(run=run).count()
        self.assertEqual(count, run.items.count())
        self.assertGreater(count, 0)

    def test_can_instantiate_multiple_runs(self):
        run_a = instantiate_checklist(self.engagement, label="Main web app")
        run_b = instantiate_checklist(self.engagement, label="REST API")
        self.assertNotEqual(run_a.pk, run_b.pk)
        self.assertEqual(
            ChecklistItem.objects.filter(run__engagement=self.engagement).count(),
            run_a.items.count() + run_b.items.count(),
        )

    def test_no_default_template_raises(self):
        ChecklistTemplate.objects.update(is_default=False)
        with self.assertRaises(ValueError):
            instantiate_checklist(self.engagement)


class ChecklistViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.outsider = make_user(User.Role.CONSULTANT)
        make_default_template()

    def test_member_can_start_checklist(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("checklist:list", args=[self.engagement.pk]), {"start_checklist": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ChecklistItem.objects.filter(run__engagement=self.engagement).exists())

    def test_non_member_cannot_view_checklist(self):
        client = Client()
        login(client, self.outsider)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_item_grouped_by_category_in_list(self):
        instantiate_checklist(self.engagement)
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Information Gathering")


class ChecklistItemDetailTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        make_default_template()
        instantiate_checklist(self.engagement)
        self.item = ChecklistItem.objects.filter(run__engagement=self.engagement).first()

    def test_update_status_and_encrypted_test_results(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]),
            {
                "save_item": "1",
                "status": ChecklistItem.Status.TESTED_NO_FINDING,
                "test_results": doc_json("Tested with Burp, no issues found."),
                "findings": [],
            },
        )
        self.assertEqual(resp.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_NO_FINDING)

        raw = bytes(self.item.test_results_ciphertext)
        self.assertNotIn(b"Burp", raw)

        key = get_data_key(self.engagement)
        plaintext = decrypt_bytes(
            raw, key, associated_data=record_aad("checklistitem", self.item.pk, "test_results"),
        ).decode()
        self.assertIn("Tested with Burp", plaintext)

    def test_reference_is_read_only_on_the_item_page(self):
        self.item.reference_info = doc_json("Check the session cookie flags.")
        self.item.save()
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]))
        html = resp.content.decode()
        self.assertIn('data-rte-field="reference_info" data-rte-editable="false"', html)
        self.assertNotIn('data-rte-hidden="reference_info"', html)

    def test_posted_reference_is_ignored(self):
        original = doc_json("Original guidance.")
        self.item.reference_info = original
        self.item.save()
        client = Client()
        login(client, self.consultant)
        payload = {
            "status": ChecklistItem.Status.TESTED_NO_FINDING,
            "reference_info": doc_json("Tampered."),
            "test_results": "",
            "findings": [],
        }
        url = reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk])
        self.assertEqual(client.post(url, {**payload, "save_item": "1"}).status_code, 302)
        autosave = reverse("checklist:item_autosave", args=[self.engagement.pk, self.item.pk])
        self.assertEqual(client.post(autosave, payload).status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.reference_info, original)

    def test_comment_encrypted_at_rest_and_listed(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_comment_create", args=[self.engagement.pk, self.item.pk]),
            {"body": doc_json("Looks fine, moving on.")},
        )
        self.assertEqual(resp.status_code, 302)

        comment = ChecklistItemComment.objects.get(checklist_item=self.item)
        self.assertEqual(comment.author, self.consultant)
        raw = bytes(comment.body_ciphertext)
        self.assertNotIn(b"Looks fine", raw)

        detail_resp = client.get(reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]))
        self.assertContains(detail_resp, "Looks fine, moving on.")

    def test_non_member_cannot_view_item(self):
        outsider = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, outsider)
        resp = client.get(reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_first_item_shows_position_and_next_link_only(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]))
        self.assertContains(resp, "Item 1 of 2")
        self.assertIsNone(resp.context["prev_item"])
        self.assertEqual(resp.context["next_item"].code, "TEST-02")

    def test_save_and_next_advances_to_next_item(self):
        second_item = ChecklistItem.objects.filter(run=self.item.run).exclude(pk=self.item.pk).get()
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk]),
            {
                "save_item": "next",
                "status": ChecklistItem.Status.TESTED_NO_FINDING,
                "test_results": "",
                "findings": [],
            },
        )
        self.assertRedirects(
            resp, reverse("checklist:item_detail", args=[self.engagement.pk, second_item.pk])
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_NO_FINDING)

    def test_save_and_next_on_last_item_returns_to_checklist_list(self):
        second_item = ChecklistItem.objects.filter(run=self.item.run).exclude(pk=self.item.pk).get()
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_detail", args=[self.engagement.pk, second_item.pk]),
            {
                "save_item": "next",
                "status": ChecklistItem.Status.NOT_APPLICABLE,
                "test_results": "",
                "findings": [],
            },
        )
        self.assertRedirects(resp, reverse("checklist:list", args=[self.engagement.pk]))

    def test_save_and_prev_goes_to_previous_item(self):
        second_item = ChecklistItem.objects.filter(run=self.item.run).exclude(pk=self.item.pk).get()
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_detail", args=[self.engagement.pk, second_item.pk]),
            {
                "save_item": "prev",
                "status": ChecklistItem.Status.NOT_APPLICABLE,
                "test_results": "",
                "findings": [],
            },
        )
        self.assertRedirects(
            resp, reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk])
        )


def doc_json_with_image(text: str) -> str:
    return json.dumps({
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            {"type": "paragraph", "content": [{"type": "image", "attrs": {"src": "/blobs/abc/"}}]},
        ],
    })


class ChecklistExportTests(TestCase):
    def setUp(self):
        from apps.findings.models import Finding

        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        make_default_template()
        run = instantiate_checklist(self.engagement, label="Main app")
        self.item = ChecklistItem.objects.filter(run=run).first()

        self.finding = Finding.objects.create(
            engagement=self.engagement, title="Reflected XSS", severity=Finding.Severity.HIGH,
            created_by=self.consultant,
        )
        self.item.findings.add(self.finding)

        key = get_data_key(self.engagement)
        self.item.test_results_ciphertext = encrypt_bytes(
            doc_json_with_image("Confirmed via manual testing.").encode(),
            key, associated_data=record_aad("checklistitem", self.item.pk, "test_results"),
        )
        self.item.save()

    def test_non_member_cannot_export(self):
        outsider = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, outsider)
        resp = client.get(reverse("checklist:export", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_export_contains_items_findings_and_strips_images(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:export", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertIn("attachment;", resp["Content-Disposition"])

        payload = json.loads(resp.content)
        self.assertEqual(payload["engagement_id"], str(self.engagement.pk))
        self.assertEqual(len(payload["runs"]), 1)

        run_payload = payload["runs"][0]
        self.assertEqual(run_payload["label"], "Main app")

        item_payload = next(i for i in run_payload["items"] if i["id"] == str(self.item.pk))
        self.assertIn("Confirmed via manual testing.", item_payload["test_results_html"])
        self.assertNotIn("<img", item_payload["test_results_html"])
        self.assertEqual(item_payload["test_results_images_omitted"], 1)
        self.assertEqual(item_payload["findings"][0]["title"], "Reflected XSS")

        self.assertGreaterEqual(payload["images_omitted_total"], 1)
        self.assertIn("not included", payload["note"])


class TemplateManagementTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN)
        self.team_lead = make_user(User.Role.TEAM_LEAD)

    def _upload(self, client, name="New Template", set_default=False):
        data = json.dumps([{"category": "Cat A", "code": "A-01", "title": "Item"}])
        upload = SimpleUploadedFile("items.json", data.encode(), content_type="application/json")
        payload = {"name": name, "description": "", "format": "json", "file": upload}
        if set_default:
            payload["set_default"] = "1"
        return client.post(reverse("checklist_templates:upload"), payload)

    def test_superadmin_can_upload_and_set_default(self):
        existing_default = make_default_template("Existing Default")
        client = Client()
        login(client, self.superadmin)
        resp = self._upload(client, set_default=True)
        self.assertEqual(resp.status_code, 302)

        template = ChecklistTemplate.objects.get(name="New Template")
        self.assertTrue(template.is_default)
        existing_default.refresh_from_db()
        self.assertFalse(existing_default.is_default)

    def test_upload_error_message_is_actually_rendered(self):
        bad_json = json.dumps([{"category": "Cat A"}])
        upload = SimpleUploadedFile("items.json", bad_json.encode(), content_type="application/json")
        client = Client()
        login(client, self.superadmin)
        resp = client.post(
            reverse("checklist_templates:upload"),
            {"name": "Bad Upload", "description": "", "format": "json", "file": upload},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "title")

    def test_team_lead_can_manage_templates(self):
        client = Client()
        login(client, self.team_lead)
        resp = self._upload(client)
        self.assertEqual(resp.status_code, 302)
        resp = client.get(reverse("checklist_templates:list"))
        self.assertEqual(resp.status_code, 200)

    def test_outsider_role_cannot_manage_templates(self):
        consultant = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, consultant)
        resp = self._upload(client)
        self.assertEqual(resp.status_code, 403)
        resp = client.get(reverse("checklist_templates:list"))
        self.assertEqual(resp.status_code, 403)

    def test_template_list_rows_link_to_detail(self):
        template = make_default_template()
        client = Client()
        login(client, self.superadmin)

        resp = client.get(reverse("checklist_templates:list"))
        self.assertContains(resp, reverse("checklist_templates:detail", args=[template.pk]))

    def test_template_detail_lists_items(self):
        template = make_default_template()
        client = Client()
        login(client, self.superadmin)

        resp = client.get(reverse("checklist_templates:detail", args=[template.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["items"]), list(template.items.all()))

    def test_export_produces_reimportable_json(self):
        template = make_default_template()
        first = template.items.order_by("order").first()
        first.reference_info = doc_json("Check the headers.")
        first.save()
        client = Client()
        login(client, self.superadmin)

        resp = client.get(reverse("checklist_templates:export", args=[template.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertIn("attachment;", resp["Content-Disposition"])

        payload = json.loads(resp.content)
        self.assertEqual(payload["format"], "redscribe-checklist-template")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["name"], template.name)
        rows = payload["items"]
        self.assertEqual(len(rows), template.items.count())
        self.assertEqual(rows[0]["title"], "Test item one")
        self.assertEqual(rows[0]["category"], "Information Gathering")
        self.assertIsInstance(rows[0]["reference_info"], dict)

        count = importer.import_json("Reimported", "", resp.content.decode(), uploaded_by=self.superadmin)
        self.assertEqual(count, template.items.count())
        original = list(template.items.order_by("order").values_list("category", "code", "title", "reference_info"))
        again = list(
            ChecklistTemplate.objects.get(name="Reimported").items.order_by("order")
            .values_list("category", "code", "title", "reference_info")
        )
        self.assertEqual([r[:3] for r in again], [r[:3] for r in original])
        # Items with no reference come back as an empty document; the rest are identical.
        self.assertEqual(json.loads(again[0][3]), json.loads(original[0][3]))
        self.assertTrue(all(not r[3] or "text" not in r[3] for r in original[1:] + again[1:]))

    def test_envelope_import_takes_name_and_description_from_file(self):
        template = make_default_template()
        template.description = "Shipped description"
        template.save()
        client = Client()
        login(client, self.superadmin)
        exported = client.get(reverse("checklist_templates:export", args=[template.pk])).content.decode()
        template.delete()

        imported, count = importer.import_file("json", "", "", exported, uploaded_by=self.superadmin)
        self.assertEqual(imported.name, template.name)
        self.assertEqual(imported.description, "Shipped description")
        self.assertEqual(count, 2)
        self.assertFalse(imported.is_default)

        # Form values win over the file's.
        other, _ = importer.import_file("json", "Renamed", "Mine", exported, uploaded_by=self.superadmin)
        self.assertEqual((other.name, other.description), ("Renamed", "Mine"))

    def test_export_requires_permission(self):
        template = make_default_template()
        consultant = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, consultant)
        resp = client.get(reverse("checklist_templates:export", args=[template.pk]))
        self.assertEqual(resp.status_code, 403)


class TemplateCreateEditTests(TestCase):
    def setUp(self):
        self.team_lead = make_user(User.Role.TEAM_LEAD)

    def test_team_lead_can_create_template(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:create"),
            {"name": "Manual Template", "description": "Built by hand", "set_default": ""},
        )
        self.assertEqual(resp.status_code, 302)
        template = ChecklistTemplate.objects.get(name="Manual Template")
        self.assertEqual(template.items.count(), 0)
        self.assertFalse(template.is_default)

    def test_create_rejects_duplicate_name(self):
        ChecklistTemplate.objects.create(name="Existing Template")
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:create"),
            {"name": "Existing Template", "description": "", "set_default": ""},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")

    def test_edit_renames_and_sets_default(self):
        existing_default = make_default_template("Existing Default")
        template = ChecklistTemplate.objects.create(name="To Rename")
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:edit", args=[template.pk]),
            {"name": "Renamed", "description": "New desc", "set_default": "1"},
        )
        self.assertEqual(resp.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.name, "Renamed")
        self.assertTrue(template.is_default)
        existing_default.refresh_from_db()
        self.assertFalse(existing_default.is_default)


class TemplateItemCrudTests(TestCase):
    def setUp(self):
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.template = ChecklistTemplate.objects.create(name="CRUD Template")
        self.item_a = ChecklistTemplateItem.objects.create(
            template=self.template, category="Cat A", code="A-01", title="First", order=1,
        )
        self.item_b = ChecklistTemplateItem.objects.create(
            template=self.template, category="Cat A", code="A-02", title="Second", order=2,
        )

    def test_add_item_appends_to_template(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:item_add", args=[self.template.pk]),
            {"category": "Cat B", "code": "B-01", "title": "New item", "reference_info": ""},
        )
        self.assertEqual(resp.status_code, 302)
        item = self.template.items.get(code="B-01")
        self.assertGreater(item.order, self.item_b.order)

    def test_edit_item_updates_fields(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:item_edit", args=[self.item_a.pk]),
            {"category": "Cat A", "code": "A-01", "title": "First (updated)", "reference_info": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.item_a.refresh_from_db()
        self.assertEqual(self.item_a.title, "First (updated)")

    def test_delete_item(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(reverse("checklist_templates:item_delete", args=[self.item_a.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ChecklistTemplateItem.objects.filter(pk=self.item_a.pk).exists())

    def test_delete_does_not_affect_already_instantiated_checklist(self):
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        instantiate_checklist(engagement, template=self.template)
        instance_item = ChecklistItem.objects.get(run__engagement=engagement, code="A-01")

        client = Client()
        login(client, self.team_lead)
        client.post(reverse("checklist_templates:item_delete", args=[self.item_a.pk]))

        instance_item.refresh_from_db()
        self.assertEqual(instance_item.title, "First")

    def test_move_up_and_down_swap_order_within_category(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("checklist_templates:item_move", args=[self.item_b.pk]), {"direction": "up"},
        )
        self.assertEqual(resp.status_code, 302)
        self.item_a.refresh_from_db()
        self.item_b.refresh_from_db()
        self.assertLess(self.item_b.order, self.item_a.order)

    def test_move_up_is_noop_at_top_of_category(self):
        client = Client()
        login(client, self.team_lead)
        client.post(reverse("checklist_templates:item_move", args=[self.item_a.pk]), {"direction": "up"})
        self.item_a.refresh_from_db()
        self.assertEqual(self.item_a.order, 1)

    def test_move_only_swaps_within_same_category(self):
        other_category_item = ChecklistTemplateItem.objects.create(
            template=self.template, category="Cat Z", code="Z-01", title="Lone item", order=99,
        )
        client = Client()
        login(client, self.team_lead)
        client.post(reverse("checklist_templates:item_move", args=[other_category_item.pk]), {"direction": "up"})
        other_category_item.refresh_from_db()
        self.item_a.refresh_from_db()
        self.item_b.refresh_from_db()
        self.assertEqual(other_category_item.order, 99)
        self.assertEqual(self.item_a.order, 1)
        self.assertEqual(self.item_b.order, 2)


class StartChecklistTemplatePickerTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.default_template = make_default_template()
        self.custom_template = ChecklistTemplate.objects.create(name="Custom")
        ChecklistTemplateItem.objects.create(
            template=self.custom_template, category="Cat A", title="Only item", order=1,
        )

    def test_start_checklist_with_explicit_template_id(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:list", args=[self.engagement.pk]),
            {"start_checklist": "1", "template_id": self.custom_template.pk},
        )
        self.assertEqual(resp.status_code, 302)
        items = ChecklistItem.objects.filter(run__engagement=self.engagement)
        self.assertEqual(items.count(), 1)
        self.assertEqual(items.first().title, "Only item")

    def test_start_checklist_without_template_id_falls_back_to_default(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(reverse("checklist:list", args=[self.engagement.pk]), {"start_checklist": "1"})
        self.assertEqual(resp.status_code, 302)
        items = ChecklistItem.objects.filter(run__engagement=self.engagement)
        self.assertGreater(items.count(), 1)

    def test_non_numeric_template_id_is_a_clean_error_not_a_500(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:list", args=[self.engagement.pk]),
            {"start_checklist": "1", "template_id": "not-a-number"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ChecklistItem.objects.filter(run__engagement=self.engagement).count(), 0)

    def test_overlong_label_is_truncated_not_a_500(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:list", args=[self.engagement.pk]),
            {"start_checklist": "1", "label": "x" * 300},
        )
        self.assertEqual(resp.status_code, 302)
        run = self.engagement.checklist_runs.get()
        self.assertEqual(len(run.label), 255)


class MultipleChecklistRunsViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        make_default_template()
        self.custom_template = ChecklistTemplate.objects.create(name="API Top 10")
        ChecklistTemplateItem.objects.create(
            template=self.custom_template, category="Auth", title="Broken object level auth", order=1,
        )

    def test_can_start_a_second_run_alongside_the_first(self):
        client = Client()
        login(client, self.consultant)
        client.post(
            reverse("checklist:list", args=[self.engagement.pk]),
            {"start_checklist": "1", "label": "Main web app"},
        )
        resp = client.post(
            reverse("checklist:list", args=[self.engagement.pk]),
            {"start_checklist": "1", "label": "REST API", "template_id": self.custom_template.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.engagement.checklist_runs.count(), 2)

    def test_list_page_shows_both_runs(self):
        instantiate_checklist(self.engagement, label="Main web app")
        instantiate_checklist(self.engagement, template=self.custom_template, label="REST API")

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["runs"]), 2)
        self.assertContains(resp, "Main web app")
        self.assertContains(resp, "REST API")

    def test_item_detail_scoped_to_its_own_run_only(self):
        run_a = instantiate_checklist(self.engagement, label="Main web app")
        run_b = instantiate_checklist(self.engagement, template=self.custom_template, label="REST API")
        item_from_b = run_b.items.first()

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:item_detail", args=[self.engagement.pk, item_from_b.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["item"].run_id, run_b.pk)
        self.assertNotEqual(resp.context["item"].run_id, run_a.pk)


class SuggestedNextCheckTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        template = ChecklistTemplate.objects.create(name="Suggestion Test Template", is_default=True)
        ChecklistTemplateItem.objects.bulk_create([
            ChecklistTemplateItem(template=template, category="Information Gathering", title="Item one", order=0),
            ChecklistTemplateItem(template=template, category="Information Gathering", title="Item two", order=1),
            ChecklistTemplateItem(template=template, category="API Testing", title="API item", order=2),
        ])
        instantiate_checklist(self.engagement)

    def test_one_suggestion_per_category_with_untouched_items(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)

        categories_with_items = ChecklistItem.objects.filter(
            run__engagement=self.engagement
        ).values_list("category", flat=True).distinct().count()
        self.assertEqual(len(resp.context["runs"][0]["suggestions"]), categories_with_items)

    def test_suggestion_is_first_untouched_item_in_category(self):
        category = ChecklistItem.objects.filter(run__engagement=self.engagement).first().category
        items_in_category = list(
            ChecklistItem.objects.filter(run__engagement=self.engagement, category=category).order_by("order")
        )
        items_in_category[0].status = ChecklistItem.Status.TESTED_NO_FINDING
        items_in_category[0].save()

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        suggestion_for_category = next(
            s for s in resp.context["runs"][0]["suggestions"] if s["category"] == category
        )
        self.assertEqual(suggestion_for_category["item"].pk, items_in_category[1].pk)

    def test_fully_tested_category_has_no_suggestion(self):
        category = ChecklistItem.objects.filter(run__engagement=self.engagement).first().category
        ChecklistItem.objects.filter(run__engagement=self.engagement, category=category).update(
            status=ChecklistItem.Status.TESTED_NO_FINDING
        )

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertFalse(any(s["category"] == category for s in resp.context["runs"][0]["suggestions"]))

    def test_suggestion_does_not_block_testing_a_different_item(self):
        not_suggested = ChecklistItem.objects.filter(
            run__engagement=self.engagement, category="API Testing"
        ).first()
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("checklist:item_detail", args=[self.engagement.pk, not_suggested.pk]),
            {
                "save_item": "1", "status": ChecklistItem.Status.NOT_APPLICABLE,
                "test_results": "", "findings": [],
            },
        )
        self.assertEqual(resp.status_code, 302)
        not_suggested.refresh_from_db()
        self.assertEqual(not_suggested.status, ChecklistItem.Status.NOT_APPLICABLE)


class _ItemPostMixin:
    """Signed-in member with one checklist item, plus post() to save its form."""

    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        make_default_template()
        instantiate_checklist(self.engagement)
        self.item = ChecklistItem.objects.filter(run__engagement=self.engagement).first()
        self.client = Client()
        login(self.client, self.consultant)
        self.url = reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk])

    def post(self, status, reason=""):
        return self.client.post(self.url, {
            "save_item": "stay", "status": status, "blocked_reason": reason,
            "test_results": "", "findings": [],
        })


class BlockedOutcomeTests(_ItemPostMixin, TestCase):
    def test_blocked_requires_a_reason(self):
        resp = self.post(ChecklistItem.Status.BLOCKED)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Say why this check couldn")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.NOT_TESTED)

    def test_blocked_reason_is_encrypted_at_rest(self):
        resp = self.post(ChecklistItem.Status.BLOCKED, "Staging XML endpoint down")
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.BLOCKED)
        raw = bytes(self.item.blocked_reason_ciphertext)
        self.assertNotIn(b"Staging", raw)
        plaintext = decrypt_bytes(
            raw, get_data_key(self.engagement),
            associated_data=record_aad("checklistitem", self.item.pk, "blocked_reason"),
        ).decode()
        self.assertEqual(plaintext, "Staging XML endpoint down")

    def test_leaving_blocked_clears_the_reason(self):
        self.post(ChecklistItem.Status.BLOCKED, "Waiting for test account")
        self.post(ChecklistItem.Status.TESTED_NO_FINDING, "Waiting for test account")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_NO_FINDING)
        self.assertIsNone(self.item.blocked_reason_ciphertext)

    def test_posture_page_lists_blocked_checks_with_reason(self):
        self.post(ChecklistItem.Status.BLOCKED, "Waiting for test account")
        resp = self.client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertContains(resp, "Waiting for test account")
        self.assertContains(resp, "posture-cell-blocked")

    def test_report_coverage_shows_reason_only_with_the_key(self):
        from apps.reports.assembly import _checklist_coverage_data

        self.post(ChecklistItem.Status.BLOCKED, "Waiting for test account")
        statuses = lambda data: [row[2] for run in data for cat in run["categories"] for row in cat["rows"]]
        with_key = statuses(_checklist_coverage_data(self.engagement, {}, get_data_key(self.engagement)))
        without_key = statuses(_checklist_coverage_data(self.engagement, {}))
        self.assertIn("Blocked: Waiting for test account", with_key)
        self.assertIn("Blocked", without_key)
        self.assertNotIn("Blocked: Waiting for test account", without_key)

    def test_export_includes_blocked_reason(self):
        self.post(ChecklistItem.Status.BLOCKED, "Waiting for test account")
        resp = self.client.get(reverse("checklist:export", args=[self.engagement.pk]))
        payload = json.loads(resp.content)
        reasons = [i["blocked_reason"] for run in payload.get("runs", []) for cat in run.get("categories", [run]) for i in cat.get("items", [])]
        self.assertIn("Waiting for test account", reasons)


class TestedByTests(_ItemPostMixin, TestCase):
    def test_outcome_change_records_who_and_when(self):
        self.post(ChecklistItem.Status.TESTED_NO_FINDING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tested_by, self.consultant)
        self.assertIsNotNone(self.item.tested_at)

    def test_resaving_the_same_outcome_keeps_the_original_time(self):
        self.post(ChecklistItem.Status.TESTED_NO_FINDING)
        self.item.refresh_from_db()
        first = self.item.tested_at
        self.post(ChecklistItem.Status.TESTED_NO_FINDING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tested_at, first)

    def test_back_to_not_tested_clears_it(self):
        self.post(ChecklistItem.Status.TESTED_NO_FINDING)
        self.post(ChecklistItem.Status.NOT_TESTED)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.tested_by)
        self.assertIsNone(self.item.tested_at)

    def test_item_page_shows_who_marked_it(self):
        self.post(ChecklistItem.Status.TESTED_NO_FINDING)
        resp = self.client.get(self.url)
        self.assertContains(resp, f"by {self.consultant}")


class AssigneeTests(_ItemPostMixin, TestCase):
    def post_with(self, **extra):
        data = {
            "save_item": "stay", "status": ChecklistItem.Status.NOT_TESTED, "blocked_reason": "",
            "test_results": "", "findings": [],
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_member_can_be_assigned(self):
        resp = self.post_with(assignee=self.consultant.pk)
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.assignee, self.consultant)

    def test_someone_without_access_cannot_be_assigned(self):
        outsider = make_user(User.Role.CONSULTANT)
        resp = self.post_with(assignee=outsider.pk)
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.assignee)

    def test_only_mine_filters_the_navigator(self):
        other = ChecklistItem.objects.filter(run=self.item.run).exclude(pk=self.item.pk).first()
        marker = f'data-nav-item="{other.pk}"'
        other.assignee = self.consultant
        other.save(update_fields=["assignee"])
        self.assertContains(self.client.get(self.url + "?mine=1"), marker)

        other.assignee = None
        other.save(update_fields=["assignee"])
        self.assertNotContains(self.client.get(self.url + "?mine=1"), marker)
        self.assertContains(self.client.get(self.url), marker)


class ScopeTestedTests(_ItemPostMixin, TestCase):
    def test_scope_tested_is_encrypted_and_shown_again(self):
        self.client.post(self.url, {
            "save_item": "stay", "status": ChecklistItem.Status.TESTED_NO_FINDING, "blocked_reason": "",
            "scope_tested": "GET /search?q\nPOST /api/orders",
            "test_results": "", "findings": [],
        })
        self.item.refresh_from_db()
        self.assertNotIn(b"/search", bytes(self.item.scope_tested_ciphertext))
        self.assertContains(self.client.get(self.url), "POST /api/orders")


class CustomCheckTests(_ItemPostMixin, TestCase):
    def add(self, **data):
        return self.client.post(reverse("checklist:list", args=[self.engagement.pk]), {"add_custom_check": "1", **data})

    def test_custom_check_is_added_to_the_end_of_the_run_only(self):
        run = self.item.run
        template_count = ChecklistTemplateItem.objects.count()
        resp = self.add(run_id=run.pk, category="Business Logic", code="CUST-01", title="PDF export SSRF")
        self.assertEqual(resp.status_code, 302)
        added = run.items.get(title="PDF export SSRF")
        self.assertEqual(added.order, max(i.order for i in run.items.all()))
        self.assertEqual(added.category, "Business Logic")
        self.assertEqual(ChecklistTemplateItem.objects.count(), template_count)

    def test_title_is_required(self):
        count = self.item.run.items.count()
        self.add(run_id=self.item.run.pk, title="  ")
        self.assertEqual(self.item.run.items.count(), count)

    def test_cannot_add_to_another_engagements_run(self):
        other = Engagement.objects.create(client_name="Other")
        generate_project_key(other)
        other_run = instantiate_checklist(other)
        resp = self.add(run_id=other_run.pk, title="Sneaky")
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(other_run.items.filter(title="Sneaky").exists())


class ActivityTests(_ItemPostMixin, TestCase):
    def save(self, **extra):
        data = {
            "save_item": "stay", "status": ChecklistItem.Status.NOT_TESTED, "blocked_reason": "", "scope_tested": "",
            "test_results": "", "findings": [],
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def kinds(self):
        from .models import ChecklistItemEvent

        return list(ChecklistItemEvent.objects.filter(item=self.item).values_list("kind", flat=True))

    def test_outcome_and_assignee_changes_are_recorded(self):
        self.save(status=ChecklistItem.Status.TESTED_NO_FINDING, assignee=self.consultant.pk)
        self.assertCountEqual(self.kinds(), ["STATUS", "ASSIGNEE"])
        resp = self.client.get(self.url)
        self.assertContains(resp, "changed the outcome")

    def test_resaving_without_changes_records_nothing(self):
        self.save(status=ChecklistItem.Status.TESTED_NO_FINDING)
        before = len(self.kinds())
        self.save(status=ChecklistItem.Status.TESTED_NO_FINDING)
        self.assertEqual(len(self.kinds()), before)

    def test_encrypted_edits_are_noted_without_their_content(self):
        from .models import ChecklistItemEvent

        self.save(scope_tested="GET /secret-admin-path")
        event = ChecklistItemEvent.objects.get(item=self.item, kind="SCOPE")
        self.assertNotIn("secret", event.from_value + event.to_value)


class AutosaveTests(_ItemPostMixin, TestCase):
    def data(self, version, **extra):
        data = {
            "version": version, "status": ChecklistItem.Status.TESTED_NO_FINDING, "blocked_reason": "",
            "scope_tested": "", "test_results": "", "findings": [],
        }
        data.update(extra)
        return data

    def version(self):
        return self.client.get(self.url).context["version"]

    def someone_else_saves(self):
        self.item.refresh_from_db()
        self.item.status = ChecklistItem.Status.NOT_APPLICABLE
        self.item.save()

    def autosave_url(self):
        return reverse("checklist:item_autosave", args=[self.engagement.pk, self.item.pk])

    def test_autosave_saves_and_returns_the_new_version(self):
        old = self.version()
        resp = self.client.post(self.autosave_url(), self.data(old))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["saved"])
        self.assertNotEqual(body["version"], old)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_NO_FINDING)
        # The returned version lets the next autosave through.
        resp = self.client.post(self.autosave_url(), self.data(body["version"], scope_tested="/api"))
        self.assertEqual(resp.status_code, 200)

    def test_autosave_refuses_to_overwrite_a_newer_save(self):
        old = self.version()
        self.someone_else_saves()
        resp = self.client.post(self.autosave_url(), self.data(old))
        self.assertEqual(resp.status_code, 409)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.NOT_APPLICABLE)

    def test_autosave_reports_invalid_input(self):
        resp = self.client.post(self.autosave_url(), self.data(self.version(), status=ChecklistItem.Status.BLOCKED))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("blocked_reason", resp.json()["errors"])

    def test_autosave_needs_engagement_access(self):
        outsider = make_user(User.Role.CONSULTANT)
        other = Client()
        login(other, outsider)
        resp = other.post(self.autosave_url(), self.data(""))
        self.assertIn(resp.status_code, (302, 403, 404))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.NOT_TESTED)

    def test_stale_form_post_shows_the_conflict_and_keeps_input(self):
        old = self.version()
        self.someone_else_saves()
        resp = self.client.post(self.url, self.data(old, save_item="next", scope_tested="GET /mine"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "saved this check after you opened it")
        self.assertContains(resp, "GET /mine")
        self.assertNotContains(resp, "data-autosave-url")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.NOT_APPLICABLE)

    def test_repeated_text_edits_show_as_one_entry(self):
        old = self.version()
        for n in range(3):
            resp = self.client.post(self.autosave_url(), self.data(old, scope_tested=f"GET /v{n}"))
            old = resp.json()["version"]
        self.assertEqual(self.item.events.filter(kind="SCOPE").count(), 1)

    def test_keep_my_changes_overwrites(self):
        old = self.version()
        self.someone_else_saves()
        resp = self.client.post(self.url, self.data(old, save_item="overwrite"))
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_NO_FINDING)


class RaiseFromCheckTests(_ItemPostMixin, TestCase):
    def create_url(self):
        return reverse("findings:create", args=[self.engagement.pk]) + f"?from_check={self.item.pk}"

    def finding_data(self, **extra):
        from apps.findings.models import ClassificationTag, Finding
        from apps.findings.tests import doc_json, section_post_key

        tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
        data = {
            "title": "IDOR on invoices", "cvss_score": "", "cvss_vector": "", "severity": Finding.Severity.HIGH,
            "cve_id": "", "status": Finding.Status.OPEN, "affects": "GET /api/invoices/{id}",
            "classification_taxonomy": [tag.taxonomy], "classification_value": [tag.value],
        }
        for name in ["vulnerability_description", "business_impact", "testing_summary", "technical_details",
                     "recommendations", "references"]:
            data[section_post_key(name)] = doc_json("")
        data[section_post_key("note")] = ""
        data[section_post_key("remediation_testing")] = ""
        data.update(extra)
        return data

    def test_form_is_prefilled_from_the_check(self):
        from .services import encrypt_item_text

        self.item.scope_tested_ciphertext = encrypt_item_text(
            self.item, "scope_tested", "GET /api/invoices/{id}", get_data_key(self.engagement),
        )
        self.item.save()
        resp = self.client.get(self.create_url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial["title"], self.item.title)
        self.assertEqual(resp.context["form"].initial["affects"], "GET /api/invoices/{id}")
        self.assertContains(resp, "Raising from checklist item")

    def test_saving_links_the_finding_and_marks_the_check(self):
        from apps.findings.models import Finding

        resp = self.client.post(self.create_url(), self.finding_data())
        self.assertEqual(resp.status_code, 302)
        finding = Finding.objects.get(title="IDOR on invoices")
        self.item.refresh_from_db()
        self.assertEqual(list(self.item.findings.all()), [finding])
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_FINDING_RAISED)
        self.assertEqual(self.item.tested_by, self.consultant)
        kinds = set(self.item.events.values_list("kind", flat=True))
        self.assertEqual(kinds, {"FINDINGS", "STATUS"})

    def test_an_already_tested_check_keeps_its_outcome(self):
        self.item.status = ChecklistItem.Status.BLOCKED
        self.item.save()
        self.client.post(self.create_url(), self.finding_data())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.BLOCKED)
        self.assertEqual(self.item.findings.count(), 1)

    def test_a_check_from_another_engagement_is_refused(self):
        other = Engagement.objects.create(client_name="Other")
        generate_project_key(other)
        EngagementMembership.objects.create(user=self.consultant, engagement=other)
        url = reverse("findings:create", args=[other.pk]) + f"?from_check={self.item.pk}"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.post(url, self.finding_data())
        self.assertEqual(self.item.findings.count(), 0)

    def test_item_page_links_to_raise(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, f"?from_check={self.item.pk}")


class BulkCategoryTests(_ItemPostMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.run = self.item.run
        self.category = self.item.category
        self.list_url = reverse("checklist:list", args=[self.engagement.pk])

    def bulk(self, status, category=None):
        return self.client.post(self.list_url, {
            "bulk_category": "1", "run_id": self.run.pk, "category": category or self.category, "status": status,
        })

    def test_marks_only_untested_checks_in_the_category(self):
        in_category = list(self.run.items.filter(category=self.category))
        self.assertGreater(len(in_category), 0)
        self.item.status = ChecklistItem.Status.TESTED_FINDING_RAISED
        self.item.save()
        other_categories = self.run.items.exclude(category=self.category)
        untouched_before = list(other_categories.values_list("pk", "status"))

        resp = self.bulk(ChecklistItem.Status.NOT_APPLICABLE)
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.TESTED_FINDING_RAISED)
        for other in self.run.items.filter(category=self.category).exclude(pk=self.item.pk):
            self.assertEqual(other.status, ChecklistItem.Status.NOT_APPLICABLE)
            self.assertEqual(other.tested_by, self.consultant)
            self.assertEqual(other.events.get().kind, "STATUS")
        self.assertEqual(list(other_categories.values_list("pk", "status")), untouched_before)

    def test_blocked_cannot_be_applied_in_bulk(self):
        self.bulk(ChecklistItem.Status.BLOCKED)
        self.assertFalse(self.run.items.filter(status=ChecklistItem.Status.BLOCKED).exists())

    def test_another_engagements_run_is_refused(self):
        other = Engagement.objects.create(client_name="Other")
        generate_project_key(other)
        other_run = instantiate_checklist(other)
        resp = self.client.post(self.list_url, {
            "bulk_category": "1", "run_id": other_run.pk, "category": self.category,
            "status": ChecklistItem.Status.NOT_APPLICABLE,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(other_run.items.exclude(status=ChecklistItem.Status.NOT_TESTED).exists())

    def test_list_offers_the_action_per_category(self):
        resp = self.client.get(self.list_url)
        self.assertContains(resp, 'name="bulk_category"')


class ItemPageShortcutTests(_ItemPostMixin, TestCase):
    def test_outcomes_navigation_and_save_have_shortcuts(self):
        resp = self.client.get(self.url)
        for n in range(1, len(ChecklistItem.Status.choices) + 1):
            self.assertContains(resp, f'data-shortcut="{n}"')
        self.assertContains(resp, 'data-shortcut="mod+enter"')
        self.assertContains(resp, 'id="shortcuts-dialog"')

    def test_item_page_is_a_focus_page(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, '<html lang="en" class="h-full" data-focus-page>')
        resp = self.client.get(reverse("checklist:list", args=[self.engagement.pk]))
        self.assertNotContains(resp, "data-focus-page>")


def _nested_doc_text(depth):
    """A doc nested `depth` levels deep, built as text so building it can't hit the recursion limit."""
    return ('{"type":"doc","content":[' + '{"type":"blockquote","content":[' * depth + '{"type":"paragraph"}'
            + ']}' * depth + ']}')


class ImportHardeningTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def _import(self, rows, name="T", **kwargs):
        return importer.import_json(name, "", json.dumps(rows), uploaded_by=self.superadmin, **kwargs)

    def test_failed_import_leaves_the_existing_template_untouched(self):
        self._import([{"category": "C", "title": "Keep me"}], name="Stable")
        with self.assertRaises(ValueError):
            self._import([{"category": "C", "title": "New"}, {"category": "C"}], name="Stable")
        self.assertEqual(
            list(ChecklistTemplateItem.objects.filter(template__name="Stable").values_list("title", flat=True)),
            ["Keep me"],
        )

    def test_nesting_near_the_json_parser_limit_is_a_clean_error(self):
        for depth in (61, 300, 700, 900, 990):
            raw = '[{"category":"C","title":"T","reference_info":' + _nested_doc_text(depth) + '}]'
            try:
                importer.import_json("Deep", "", raw, uploaded_by=self.superadmin)
            except ValueError:
                pass  # rejected cleanly: fine

    def test_nested_doc_given_as_a_string_is_rejected_too(self):
        rows = [{"category": "C", "title": "T", "reference_info": _nested_doc_text(200)}]
        with self.assertRaisesMessage(ValueError, "Row 1"):
            self._import(rows)

    def test_overlong_fields_are_a_row_error_not_a_database_error(self):
        for field, size in (("code", 33), ("category", 256), ("title", 501)):
            row = {"category": "C", "title": "T", "code": "", field: "x" * size}
            with self.assertRaisesMessage(ValueError, "Row 1"):
                self._import([row])
        with self.assertRaises(ValueError):
            self._import([{"category": "C", "title": "T"}], name="n" * 256)

    def test_non_text_values_are_rejected_not_stringified(self):
        for bad in ({"a": 1}, ["x"], True):
            with self.assertRaisesMessage(ValueError, "Row 1"):
                self._import([{"category": bad, "title": "T"}])

    def test_numbers_are_accepted_as_codes(self):
        self._import([{"category": "C", "title": "T", "code": 42}], name="Numeric")
        self.assertEqual(ChecklistTemplateItem.objects.get(template__name="Numeric").code, "42")

    def test_version_must_be_a_real_integer(self):
        for version in (True, "1", 1.5, 0, -1):
            with self.assertRaisesMessage(ValueError, "version"):
                importer.import_json("N", "", json.dumps({"version": version, "items": []}), uploaded_by=self.superadmin)

    def test_is_default_in_the_file_is_ignored(self):
        payload = {"name": "Sneaky", "is_default": True, "items": [{"category": "C", "title": "T"}]}
        template, _ = importer.import_file("json", "", "", json.dumps(payload), uploaded_by=self.superadmin)
        self.assertFalse(template.is_default)

    def test_csv_cells_are_cleaned_like_json(self):
        doc = json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]},
        ]}]})
        buf = io.StringIO()
        csv.writer(buf).writerows([["category", "title", "reference_info"], ["C", "T", doc], ["C", "T2", "plain"]])
        importer.import_csv("Csv", "", buf.getvalue(), uploaded_by=self.superadmin)
        first, second = ChecklistTemplateItem.objects.filter(template__name="Csv").order_by("order")
        self.assertNotIn("javascript", first.reference_info)
        self.assertIn("plain", second.reference_info)

    def test_csv_without_a_name_is_an_error(self):
        with self.assertRaisesMessage(ValueError, "name"):
            importer.import_file("csv", "", "", "category,title\nC,T\n", uploaded_by=self.superadmin)

    def test_legacy_plain_text_reference_exports_and_reimports(self):
        template = ChecklistTemplate.objects.create(name="Legacy")
        ChecklistTemplateItem.objects.create(template=template, category="C", title="T", reference_info="just text")
        payload = json.loads(importer.export_json(template))
        self.assertEqual(payload["items"][0]["reference_info"], "just text")
        importer.import_json("Legacy2", "", json.dumps(payload), uploaded_by=self.superadmin)
        self.assertIn("just text", ChecklistTemplateItem.objects.get(template__name="Legacy2").reference_info)

    def test_content_that_is_not_a_list_is_not_treated_as_a_document(self):
        rows = [{"category": "C", "title": "T", "reference_info": '{"type":"doc","content":"oops"}'}]
        self._import(rows, name="Odd")
        stored = ChecklistTemplateItem.objects.get(template__name="Odd").reference_info
        self.assertIsInstance(json.loads(stored)["content"], list)


class UploadViewHardeningTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN)
        self.consultant = make_user(User.Role.CONSULTANT)

    def _post(self, client, payload, name="", **extra):
        upload = SimpleUploadedFile("t.json", json.dumps(payload).encode(), content_type="application/json")
        data = {"name": name, "description": "", "format": "json", "file": upload, **extra}
        return client.post(reverse("checklist_templates:upload"), data)

    def test_blank_name_takes_the_name_from_the_file(self):
        client = Client(); login(client, self.superadmin)
        resp = self._post(client, {"name": "From File", "items": [{"category": "C", "title": "T"}]})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ChecklistTemplate.objects.filter(name="From File").exists())

    def test_file_cannot_silently_replace_an_existing_template(self):
        existing = make_default_template("Shared Library")
        client = Client(); login(client, self.superadmin)
        resp = self._post(client, {"name": "Shared Library", "items": [{"category": "C", "title": "Injected"}]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(existing.items.count(), 2)
        self.assertFalse(existing.items.filter(title="Injected").exists())

    def test_typing_the_name_confirms_replacing_an_existing_template(self):
        existing = make_default_template("Shared Library")
        client = Client(); login(client, self.superadmin)
        resp = self._post(
            client, {"name": "Shared Library", "items": [{"category": "C", "title": "Replacement"}]},
            name="Shared Library",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(list(existing.items.values_list("title", flat=True)), ["Replacement"])

    def test_overlong_name_in_file_is_a_form_error(self):
        client = Client(); login(client, self.superadmin)
        resp = self._post(client, {"name": "n" * 300, "items": []})
        self.assertEqual(resp.status_code, 200)

    def test_consultant_cannot_upload_or_export_templates(self):
        template = make_default_template("Guarded")
        client = Client(); login(client, self.consultant)
        self.assertEqual(self._post(client, {"name": "X", "items": []}).status_code, 403)
        self.assertFalse(ChecklistTemplate.objects.filter(name="X").exists())
        self.assertEqual(client.get(reverse("checklist_templates:export", args=[template.pk])).status_code, 403)

    def test_anonymous_cannot_upload_or_export(self):
        template = make_default_template("Guarded")
        client = Client()
        self.assertEqual(self._post(client, {"name": "X", "items": []}).status_code, 302)
        self.assertEqual(client.get(reverse("checklist_templates:export", args=[template.pk])).status_code, 302)
        self.assertFalse(ChecklistTemplate.objects.filter(name="X").exists())


class ReferenceReadOnlyHardeningTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        make_default_template()
        instantiate_checklist(self.engagement)
        self.item = ChecklistItem.objects.filter(run__engagement=self.engagement).first()
        self.client = Client(); login(self.client, self.consultant)
        self.url = reverse("checklist:item_detail", args=[self.engagement.pk, self.item.pk])

    def test_reference_text_cannot_break_out_of_its_attribute(self):
        evil = "'><script>alert(1)</script><img src=x onerror=alert(1)>"
        self.item.reference_info = doc_json(evil)
        self.item.save()
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty_reference_shows_a_placeholder_and_no_editor(self):
        self.item.reference_info = ""
        self.item.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn("No reference guidance", html)
        self.assertNotIn('data-rte-field="reference_info"', html)

    def test_other_fields_still_save_and_reference_survives(self):
        original = doc_json("Keep this guidance.")
        self.item.reference_info = original
        self.item.save()
        resp = self.client.post(self.url, {
            "save_item": "1", "status": ChecklistItem.Status.NOT_APPLICABLE,
            "scope_tested": "GET /x", "test_results": doc_json("results"), "findings": [],
        })
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ChecklistItem.Status.NOT_APPLICABLE)
        self.assertEqual(self.item.reference_info, original)

    def test_reference_cannot_be_changed_via_the_other_engagements_item(self):
        other = Engagement.objects.create(client_name="Other")
        generate_project_key(other)
        resp = self.client.post(
            reverse("checklist:item_autosave", args=[other.pk, self.item.pk]),
            {"status": ChecklistItem.Status.NOT_APPLICABLE, "reference_info": doc_json("x"), "findings": []},
        )
        self.assertIn(resp.status_code, (403, 404))
        self.item.refresh_from_db()
        self.assertNotIn('"x"', self.item.reference_info)

    def test_new_runs_still_copy_the_template_reference(self):
        template = ChecklistTemplate.objects.get(name="Default Template")
        first = template.items.order_by("order").first()
        first.reference_info = doc_json("Template says hello")
        first.save()
        second_engagement = Engagement.objects.create(client_name="Fresh")
        generate_project_key(second_engagement)
        instantiate_checklist(second_engagement)
        copied = ChecklistItem.objects.filter(run__engagement=second_engagement, title=first.title).first()
        self.assertIn("Template says hello", copied.reference_info)
