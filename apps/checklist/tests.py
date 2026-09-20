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
                "reference_info": self.item.reference_info,
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
                "reference_info": self.item.reference_info,
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
                "reference_info": second_item.reference_info,
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
                "reference_info": second_item.reference_info,
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
        client = Client()
        login(client, self.superadmin)

        resp = client.get(reverse("checklist_templates:export", args=[template.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertIn("attachment;", resp["Content-Disposition"])

        rows = json.loads(resp.content)
        self.assertEqual(len(rows), template.items.count())
        self.assertEqual(rows[0]["title"], "Test item one")
        self.assertEqual(rows[0]["category"], "Information Gathering")

        count = importer.import_json(
            "Reimported", "", json.dumps(rows), uploaded_by=self.superadmin,
        )
        self.assertEqual(count, template.items.count())

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
                "reference_info": not_suggested.reference_info, "test_results": "", "findings": [],
            },
        )
        self.assertEqual(resp.status_code, 302)
        not_suggested.refresh_from_db()
        self.assertEqual(not_suggested.status, ChecklistItem.Status.NOT_APPLICABLE)
