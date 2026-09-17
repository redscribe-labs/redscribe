from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notification

PAGE_SIZE = 20


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user).select_related(
        "actor", "finding__engagement", "engagement"
    )
    page_obj = Paginator(notifications, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request, "notifications/list.html",
        {"page_obj": page_obj, "breadcrumbs": [{"label": "Notifications"}]},
    )


@login_required
def notification_open(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.read:
        notification.read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["read", "read_at"])

    if notification.finding_id:
        return redirect("findings:detail", engagement_id=notification.finding.engagement_id, pk=notification.finding_id)
    if notification.engagement_id:
        return redirect("engagements:detail", engagement_id=notification.engagement_id)
    return redirect("notifications:list")


@require_POST
@login_required
def notification_mark_all_read(request):
    Notification.objects.filter(recipient=request.user, read=False).update(read=True, read_at=timezone.now())
    messages.success(request, "All notifications marked as read.")

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(reverse("notifications:list"))
