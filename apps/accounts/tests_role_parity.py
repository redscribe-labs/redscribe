"""Empirical parity check for the permission model.

A custom role with the *same permissions* as a built-in role must receive the
*same privileges* everywhere the backend enforces authorization — otherwise some
capability is keyed off a hardcoded role check rather than a permission.

These tests clone each built-in role's permission set onto a fresh custom role
and compare a battery of authorization outcomes. For the non-superadmin roles the
two must match exactly. For Superadmin they diverge only where a capability is
still gated by a hardcoded ``is_superadmin_role`` check with no backing permission
— those are enumerated so the gaps are explicit.
"""
import os

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.crypto.services import generate_project_key
from apps.engagements import access as eaccess
from apps.engagements import permissions as eperm
from apps.engagements.models import Engagement, EngagementMembership
from apps.findings import permissions as fperm
from apps.findings import review
from apps.findings.models import Finding, VulnerabilityTemplate

from .models import Role

User = get_user_model()


def _mk_user(role):
    tag = os.urandom(4).hex()
    user = User.objects.create(
        username=f"u-{role.slug}-{tag}", email=f"{tag}@example.com",
        role=role, auth_type=User.AuthType.LOCAL,
    )
    user.set_password("pw")
    user.save()
    return user


def _clone_role(builtin):
    custom = Role.objects.create(name=f"Custom {builtin.name} {os.urandom(2).hex()}")
    custom.permissions.set(builtin.permissions.all())
    return custom


def _capabilities(user, *, eng, archived_eng, other_template, other_finding):
    own = Finding.objects.create(
        engagement=eng, title="Own", severity=Finding.Severity.HIGH, created_by=user,
    )
    caps = {
        "can_create_engagement": eperm.can_create_engagement(user),
        "is_engagement_manager": eperm.is_engagement_manager(user, eng),
        "can_archive_engagement": eperm.can_archive_engagement(user, eng),
        "can_release_to_client": eperm.can_release_engagement_to_client(user, eng),
        "can_permanently_delete_engagement": eperm.can_permanently_delete_engagement(user),
        "access_member_eng": eaccess.check_engagement_access(user, eng).granted,
        "access_archived_eng": eaccess.check_engagement_access(user, archived_eng).granted,
        "sees_archived_in_visible": archived_eng in eaccess.visible_engagements(user),
        "can_create_catalogue_entry": fperm.can_create_catalogue_entry(user),
        "can_approve_catalogue_entry": fperm.can_approve_catalogue_entry(user),
        "can_bulk_manage_catalogue": fperm.can_bulk_manage_catalogue(user),
        "can_edit_other_template": fperm.can_edit_catalogue_entry(user, other_template),
        "can_delete_other_template": fperm.can_delete_catalogue_entry(user, other_template),
        "eligible_reviewer_other": review.is_eligible_reviewer(user, other_finding),
        "eligible_qa_other": review.is_eligible_qa_reviewer(user, other_finding),
        "eligible_reviewer_own": review.is_eligible_reviewer(user, own),
        "eligible_qa_own": review.is_eligible_qa_reviewer(user, own),
    }
    own.delete()
    return caps


class RolePermissionParityTests(TestCase):
    def setUp(self):
        self.eng = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.eng)
        self.archived_eng = Engagement.objects.create(client_name="Old", archived=True)
        generate_project_key(self.archived_eng)
        self.third_party = _mk_user(Role.objects.get(slug="consultant"))
        self.other_template = VulnerabilityTemplate.objects.create(
            title="T", default_severity=Finding.Severity.HIGH, created_by=self.third_party,
        )
        self.other_finding = Finding.objects.create(
            engagement=self.eng, title="Other", severity=Finding.Severity.HIGH,
            created_by=self.third_party,
        )

    def _divergences(self, builtin_slug):
        builtin = Role.objects.get(slug=builtin_slug)
        custom = _clone_role(builtin)
        bu, cu = _mk_user(builtin), _mk_user(custom)
        EngagementMembership.objects.create(user=bu, engagement=self.eng)
        EngagementMembership.objects.create(user=cu, engagement=self.eng)
        kw = dict(
            eng=self.eng, archived_eng=self.archived_eng,
            other_template=self.other_template, other_finding=self.other_finding,
        )
        b, c = _capabilities(bu, **kw), _capabilities(cu, **kw)
        return {k: (b[k], c[k]) for k in b if b[k] != c[k]}

    def test_team_lead_custom_role_has_full_parity(self):
        self.assertEqual(self._divergences("team_lead"), {})

    def test_senior_custom_role_has_full_parity(self):
        self.assertEqual(self._divergences("senior"), {})

    def test_consultant_custom_role_has_full_parity(self):
        self.assertEqual(self._divergences("consultant"), {})

    def test_superadmin_custom_role_has_full_parity(self):
        # Every capability in this backend matrix is now permission-gated, so a custom
        # role cloned from Superadmin's permission set matches it exactly. The only
        # capabilities still reserved for the is_superadmin flag are deliberately out of
        # this matrix: assigning the Superadmin role itself (an escalation guard) — see
        # _staff_role_queryset.
        self.assertEqual(self._divergences("superadmin"), {})
