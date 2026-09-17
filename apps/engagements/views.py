from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.lifecycle import deactivate_dormant_client_users
from apps.clients.permissions import require_client_manager
from apps.crypto.services import generate_project_key
from apps.notifications.services import notify_scope_change_approved, notify_scope_change_rejected

from . import lifecycle
from .access import check_engagement_access, visible_engagements
from .breadcrumbs import engagement_crumbs
from .forms import AddMemberForm, EngagementCreateForm, EngagementEditForm, ScopeChangeRequestForm
from .models import Engagement, EngagementMembership, EngagementStatusHistory, ScopeChangeRequest
from .permissions import (
    can_archive_engagement,
    can_create_engagement,
    can_permanently_delete_engagement,
    can_release_engagement_to_client,
    is_engagement_manager,
)

PAGE_SIZE = 10


def _grant_access_for_default_roles(engagement: Engagement, *, granted_by) -> None:
    for user in {engagement.default_reviewer, engagement.default_qa, engagement.default_approver}:
        if user is not None:
            EngagementMembership.objects.get_or_create(
                user=user, engagement=engagement, defaults={"added_by": granted_by}
            )


@login_required
def engagement_list(request):
    query = request.GET.get("q", "").strip()
    engagements = visible_engagements(request.user)
    if query:
        engagements = engagements.filter(
            Q(client_name__icontains=query) | Q(reference_number__icontains=query)
        )

    page_obj = Paginator(engagements, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "engagements/list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "can_create": can_create_engagement(request.user),
            "breadcrumbs": [{"label": "Engagements"}],
        },
    )


@login_required
def engagement_create(request):
    if not can_create_engagement(request.user):
        raise PermissionDenied("Your role cannot create engagements.")

    try:
        require_client_manager(request.user, "create an engagement")
    except PermissionDenied:
        raise PermissionDenied(
            "Engagement creation requires linking a client company, which is restricted to "
            "Superadmin/Team Lead. Ask a Superadmin to grant this role Team Lead-equivalent "
            "client access, or create the engagement as a Team Lead/Superadmin instead."
        )

    if request.method == "POST":
        form = EngagementCreateForm(request.POST, requesting_user=request.user)
        if form.is_valid():
            engagement = form.save(commit=False)
            engagement.client_name = engagement.client.name
            engagement.created_by = request.user
            engagement.status = Engagement.Status.IN_PROGRESS
            engagement.save()
            EngagementStatusHistory.objects.create(
                engagement=engagement, status=engagement.status, changed_by=request.user,
            )

            generate_project_key(engagement)
            _grant_access_for_default_roles(engagement, granted_by=request.user)

            if not request.user.has_permission("engagements.view_all"):
                EngagementMembership.objects.create(
                    user=request.user, engagement=engagement, added_by=request.user
                )

            messages.success(request, f"Engagement '{engagement.client_name}' created.")
            return redirect("engagements:detail", engagement_id=engagement.pk)
    else:
        form = EngagementCreateForm(requesting_user=request.user)

    return render(
        request,
        "engagements/create.html",
        {
            "form": form,
            "breadcrumbs": [
                {"label": "Engagements", "url": reverse("engagements:list")},
                {"label": "New Engagement"},
            ],
        },
    )


@login_required
def engagement_detail(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    decision = check_engagement_access(request.user, engagement)
    if not decision.granted:
        raise PermissionDenied(decision.reason)

    is_manager = is_engagement_manager(request.user, engagement)
    members = engagement.memberships.select_related("user", "added_by").order_by("user__username")
    scope_requests = engagement.scope_change_requests.select_related("requested_by", "reviewed_by")[:20]

    from apps.checklist.models import ChecklistItem
    from apps.findings.models import Finding
    from apps.reports.services import PUBLISHABLE_STATUSES

    findings_qs = engagement.findings.all()
    findings_summary = {
        "total": findings_qs.count(),
        "open": findings_qs.filter(status=Finding.Status.OPEN).count(),
        "publishable": findings_qs.filter(workflow_status__in=PUBLISHABLE_STATUSES).count(),
    }

    checklist_items = ChecklistItem.objects.filter(run__engagement=engagement)
    checklist_total = checklist_items.count()
    checklist_tested = checklist_items.exclude(status=ChecklistItem.Status.NOT_TESTED).count()
    checklist_summary = {
        "started": checklist_total > 0,
        "total": checklist_total,
        "tested": checklist_tested,
        "pct": round(checklist_tested / checklist_total * 100) if checklist_total else 0,
    }

    return render(
        request,
        "engagements/detail.html",
        {
            "engagement": engagement,
            "members": members,
            "scope_requests": scope_requests,
            "is_manager": is_manager,
            "can_release_to_client": can_release_engagement_to_client(request.user, engagement),
            "add_member_form": AddMemberForm(engagement=engagement) if is_manager else None,
            "scope_change_form": ScopeChangeRequestForm(),
            "transition_options": lifecycle.visible_transition_options(request.user, engagement),
            "findings_summary": findings_summary,
            "checklist_summary": checklist_summary,
            "breadcrumbs": [
                {"label": "Engagements", "url": reverse("engagements:list")},
                {"label": engagement.client_name},
            ],
        },
    )


@login_required
def engagement_edit(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not is_engagement_manager(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can edit this engagement.")

    if request.method == "POST":
        form = EngagementEditForm(request.POST, instance=engagement, requesting_user=request.user)
        if form.is_valid():
            form.save()
            _grant_access_for_default_roles(engagement, granted_by=request.user)
            messages.success(request, "Engagement updated.")
            return redirect("engagements:detail", engagement_id=engagement.pk)
    else:
        form = EngagementEditForm(instance=engagement, requesting_user=request.user)

    return render(
        request,
        "engagements/edit.html",
        {
            "form": form,
            "engagement": engagement,
            "breadcrumbs": engagement_crumbs(engagement) + [{"label": "Edit"}],
        },
    )


@require_POST
@login_required
def engagement_transition(request, engagement_id, to_status):
    if to_status not in Engagement.Status.values:
        return HttpResponseBadRequest("Invalid status.")

    with transaction.atomic():
        engagement = get_object_or_404(
            Engagement.objects.select_for_update(), pk=engagement_id
        )
        if not lifecycle.can_act_on_transition(request.user, engagement, to_status):
            raise PermissionDenied(lifecycle.denied_message(engagement, to_status))
        if engagement.archived or to_status not in lifecycle.available_transitions(engagement):
            raise PermissionDenied(
                f"Can't move from {engagement.get_status_display()} to "
                f"{dict(Engagement.Status.choices)[to_status]}."
            )

        lifecycle.transition_engagement(engagement, to_status, actor=request.user)

    messages.success(request, f"Engagement moved to {dict(Engagement.Status.choices)[to_status]}.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def engagement_archive(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not can_archive_engagement(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can archive this engagement.")

    if engagement.archived:
        messages.info(request, f"'{engagement.client_name}' is already archived.")
        return redirect("engagements:detail", engagement_id=engagement.pk)

    if request.method == "POST":
        engagement.archived = True
        engagement.archived_at = timezone.now()
        engagement.save(update_fields=["archived", "archived_at"])
        deactivate_dormant_client_users(engagement.client)
        messages.success(request, f"'{engagement.client_name}' archived.")
        return redirect("engagements:detail", engagement_id=engagement.pk)

    return render(request, "engagements/archive_confirm.html", {"engagement": engagement})


@login_required
def engagement_unarchive(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not can_archive_engagement(request.user, engagement):
        raise PermissionDenied("Only a Superadmin can unarchive this engagement.")

    if request.method == "POST":
        engagement.archived = False
        engagement.archived_at = None
        engagement.save(update_fields=["archived", "archived_at"])
        messages.success(request, f"'{engagement.client_name}' unarchived.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def engagement_release_to_client(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not can_release_engagement_to_client(request.user, engagement):
        raise PermissionDenied("Only a Superadmin, Team Lead, or QA reviewer can release an engagement to the client.")

    if request.method == "POST":
        engagement.client_release_approved = True
        engagement.client_release_approved_at = timezone.now()
        engagement.client_release_approved_by = request.user
        engagement.save(update_fields=[
            "client_release_approved", "client_release_approved_at", "client_release_approved_by",
        ])
        messages.success(request, f"'{engagement.client_name}' released to the client portal.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def engagement_revoke_client_release(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not can_release_engagement_to_client(request.user, engagement):
        raise PermissionDenied("Only a Superadmin, Team Lead, or QA reviewer can revoke a client release.")

    if request.method == "POST":
        engagement.client_release_approved = False
        engagement.client_release_approved_at = None
        engagement.client_release_approved_by = None
        engagement.save(update_fields=[
            "client_release_approved", "client_release_approved_at", "client_release_approved_by",
        ])
        messages.success(request, f"'{engagement.client_name}' is no longer visible in the client portal.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def engagement_permanent_delete(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not can_permanently_delete_engagement(request.user):
        raise PermissionDenied("Only a Superadmin can permanently delete an engagement.")

    if not engagement.archived:
        messages.error(request, "Archive this engagement before it can be permanently deleted.")
        return redirect("engagements:detail", engagement_id=engagement.pk)

    if request.method == "POST":
        if request.POST.get("confirm_client_name") != engagement.client_name:
            messages.error(request, "Client name didn't match — nothing was deleted.")
            return render(request, "engagements/permanent_delete_confirm.html", {"engagement": engagement})
        client_name = engagement.client_name
        engagement.delete()
        messages.success(request, f"'{client_name}' was permanently deleted.")
        return redirect("engagements:list")

    return render(request, "engagements/permanent_delete_confirm.html", {"engagement": engagement})


@login_required
def member_add(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not is_engagement_manager(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can manage engagement membership.")

    if request.method == "POST":
        form = AddMemberForm(request.POST, engagement=engagement)
        if form.is_valid():
            EngagementMembership.objects.create(
                user=form.cleaned_data["user"], engagement=engagement, added_by=request.user
            )
            messages.success(request, f"{form.cleaned_data['user']} added to the engagement.")
        else:
            messages.error(request, " ".join(form.errors.get("user", ["Couldn't add that member."])))
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def member_remove(request, engagement_id, membership_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not is_engagement_manager(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can manage engagement membership.")

    membership = get_object_or_404(EngagementMembership, pk=membership_id, engagement=engagement)
    if request.method == "POST":
        removed_user = membership.user
        membership.delete()
        messages.success(request, f"{removed_user} removed from the engagement.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def scope_change_create(request, engagement_id):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    decision = check_engagement_access(request.user, engagement)
    if not decision.granted:
        raise PermissionDenied(decision.reason)

    if request.method == "POST":
        form = ScopeChangeRequestForm(request.POST)
        if form.is_valid():
            ScopeChangeRequest.objects.create(
                engagement=engagement,
                proposed_scope=form.cleaned_data["proposed_scope"],
                requested_by=request.user,
            )
            messages.success(request, "Scope change proposed, awaiting Team Lead approval.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def scope_change_approve(request, engagement_id, pk):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not is_engagement_manager(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can approve scope changes.")

    scope_request = get_object_or_404(
        ScopeChangeRequest, pk=pk, engagement=engagement, status=ScopeChangeRequest.Status.PENDING
    )
    if request.method == "POST":
        engagement.scope = scope_request.proposed_scope
        engagement.save(update_fields=["scope", "updated_at"])

        scope_request.status = ScopeChangeRequest.Status.APPROVED
        scope_request.reviewed_by = request.user
        scope_request.reviewed_at = timezone.now()
        scope_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        notify_scope_change_approved(scope_request, actor=request.user)

        messages.success(request, "Scope change approved and applied.")
    return redirect("engagements:detail", engagement_id=engagement.pk)


@login_required
def scope_change_reject(request, engagement_id, pk):
    engagement = get_object_or_404(Engagement, pk=engagement_id)
    if not is_engagement_manager(request.user, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can reject scope changes.")

    scope_request = get_object_or_404(
        ScopeChangeRequest, pk=pk, engagement=engagement, status=ScopeChangeRequest.Status.PENDING
    )
    if request.method == "POST":
        scope_request.status = ScopeChangeRequest.Status.REJECTED
        scope_request.reviewed_by = request.user
        scope_request.reviewed_at = timezone.now()
        scope_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        notify_scope_change_rejected(scope_request, actor=request.user)

        messages.info(request, "Scope change rejected.")
    return redirect("engagements:detail", engagement_id=engagement.pk)
