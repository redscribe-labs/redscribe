from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.crypto.access import engagement_access_required

from . import review
from .models import Finding


def _get_finding(request, pk):
    return get_object_or_404(Finding, pk=pk, engagement=request.engagement)


@require_POST
@engagement_access_required
def assign_reviewer(request, engagement_id, pk):
    finding = _get_finding(request, pk)
    reviewer = get_object_or_404(
        review.eligible_reviewer_candidates(finding, assigned_by=request.user), pk=request.POST.get("reviewer")
    )
    review.assign_reviewer(finding, reviewer, assigned_by=request.user)
    messages.success(request, f"{reviewer} assigned as reviewer.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)


@require_POST
@engagement_access_required
def submit_review(request, engagement_id, pk):
    finding = _get_finding(request, pk)
    outcome = request.POST.get("outcome")
    try:
        review.submit_review(finding, request.user, outcome)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, f"Review submitted: {finding.get_workflow_status_display()}.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)


@require_POST
@engagement_access_required
def assign_qa(request, engagement_id, pk):
    finding = _get_finding(request, pk)
    qa_reviewer = get_object_or_404(
        review.eligible_qa_candidates(finding, assigned_by=request.user), pk=request.POST.get("qa_reviewer")
    )
    review.assign_qa(finding, qa_reviewer, assigned_by=request.user)
    messages.success(request, f"{qa_reviewer} assigned for QA.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)


@require_POST
@engagement_access_required
def submit_qa(request, engagement_id, pk):
    finding = _get_finding(request, pk)
    outcome = request.POST.get("outcome")
    try:
        review.submit_qa(finding, request.user, outcome)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, f"QA submitted: {finding.get_workflow_status_display()}.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)


@require_POST
@engagement_access_required
def reopen_to_draft(request, engagement_id, pk):
    finding = _get_finding(request, pk)
    review.reopen_to_draft(finding, request.user)
    messages.success(request, "Finding reverted to Draft.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)


@require_POST
@engagement_access_required
def bulk_assign_reviewer(request, engagement_id):
    reviewer = get_object_or_404(review.bulk_eligible_reviewer_candidates(), pk=request.POST.get("reviewer"))
    assigned, skipped = review.bulk_assign_reviewer(request.engagement, reviewer, assigned_by=request.user)
    if assigned:
        messages.success(request, f"{reviewer} assigned as reviewer on {len(assigned)} finding{'s' if len(assigned) != 1 else ''}.")
    if skipped:
        messages.warning(
            request,
            f"{reviewer} isn't an eligible reviewer for {len(skipped)} finding{'s' if len(skipped) != 1 else ''} "
            "(most likely, they authored it) — those were left unassigned.",
        )
    if not assigned and not skipped:
        messages.info(request, "No findings are currently awaiting review assignment.")
    return redirect("findings:list", engagement_id=engagement_id)


@require_POST
@engagement_access_required
def bulk_submit_review(request, engagement_id):
    outcome = request.POST.get("outcome")
    try:
        updated, skipped = review.bulk_submit_review(request.engagement, request.user, outcome)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if updated:
        messages.success(request, f"Review submitted for {len(updated)} finding{'s' if len(updated) != 1 else ''}.")
    else:
        messages.info(request, "No findings are currently awaiting your review.")
    return redirect("findings:list", engagement_id=engagement_id)


@require_POST
@engagement_access_required
def bulk_assign_qa(request, engagement_id):
    qa_reviewer = get_object_or_404(review.bulk_eligible_qa_candidates(), pk=request.POST.get("qa_reviewer"))
    assigned, skipped = review.bulk_assign_qa(request.engagement, qa_reviewer, assigned_by=request.user)
    if assigned:
        messages.success(request, f"{qa_reviewer} assigned for QA on {len(assigned)} finding{'s' if len(assigned) != 1 else ''}.")
    if skipped:
        messages.warning(
            request,
            f"{qa_reviewer} isn't an eligible QA reviewer for {len(skipped)} finding{'s' if len(skipped) != 1 else ''} "
            "(most likely, they authored it) — those were left unassigned.",
        )
    if not assigned and not skipped:
        messages.info(request, "No findings are currently awaiting QA assignment.")
    return redirect("findings:list", engagement_id=engagement_id)


@require_POST
@engagement_access_required
def bulk_submit_qa(request, engagement_id):
    outcome = request.POST.get("outcome")
    try:
        updated, skipped = review.bulk_submit_qa(request.engagement, request.user, outcome)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if updated:
        messages.success(request, f"QA submitted for {len(updated)} finding{'s' if len(updated) != 1 else ''}.")
    else:
        messages.info(request, "No findings are currently awaiting your QA.")
    return redirect("findings:list", engagement_id=engagement_id)


@login_required
def my_queue(request):
    to_review, to_qa = review.assignments_for_user(request.user)
    return render(request, "findings/my_queue.html", {"to_review": to_review, "to_qa": to_qa})
