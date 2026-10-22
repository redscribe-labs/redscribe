import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.permissions import require_permission

from .models import AuditLogEntry
from .retention import purge_all, purge_older_than

CLEAR_ALL_CONFIRM_PHRASE = "DELETE ALL LOGS"

DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_CHOICES = [25, 50, 100, 250]

STATUS_BUCKETS = {
    "2xx": (200, 299),
    "3xx": (300, 399),
    "4xx": (400, 499),
    "5xx": (500, 599),
}


def _filtered_entries(request):
    """Entries matching the list page's filters (shared with the CSV export)."""
    query = request.GET.get("q", "").strip()
    method = request.GET.get("method", "").strip()
    actor = request.GET.get("actor", "").strip()
    status_bucket = request.GET.get("status", "").strip()
    date_from = parse_date(request.GET.get("from", "").strip())
    date_to = parse_date(request.GET.get("to", "").strip())

    entries = AuditLogEntry.objects.select_related("actor")
    if query:
        entries = entries.filter(
            Q(actor_username__icontains=query)
            | Q(action__icontains=query)
            | Q(path__icontains=query)
            | Q(object_ref__icontains=query)
            | Q(ip_address__icontains=query)
            | Q(user_agent__icontains=query)
            | Q(referer__icontains=query)
        )
    if method:
        entries = entries.filter(method=method)
    if actor:
        entries = entries.filter(actor_username=actor)
    if status_bucket in STATUS_BUCKETS:
        low, high = STATUS_BUCKETS[status_bucket]
        entries = entries.filter(status_code__gte=low, status_code__lte=high)
    if date_from:
        entries = entries.filter(created_at__date__gte=date_from)
    if date_to:
        entries = entries.filter(created_at__date__lte=date_to)
    filters = {"query": query, "method": method, "actor": actor, "status_bucket": status_bucket}
    return entries.order_by("-created_at"), filters


CSV_COLUMNS = [
    ("created_at", "Time (UTC)"), ("actor_username", "User"), ("actor_role", "Role"), ("action", "Action"),
    ("method", "Method"), ("path", "Path"), ("query_string", "Query"), ("status_code", "Status"),
    ("engagement_id", "Engagement"), ("object_ref", "Object"), ("ip_address", "IP address"),
    ("user_agent", "User agent"), ("referer", "Referer"), ("duration_ms", "Duration (ms)"),
    ("entry_hash", "Entry hash"),
]


def _csv_cell(value):
    """Spreadsheet-safe text: a leading = + - @ (or tab/CR) would otherwise be
    run as a formula when someone opens the export in Excel or Sheets."""
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class _Echo:
    def write(self, value):
        return value


@login_required
def audit_log_export(request):
    """The filtered log as CSV, streamed so a large log doesn't sit in memory."""
    require_permission(request.user, "audit_log.manage", "export the audit log")
    entries, _ = _filtered_entries(request)
    writer = csv.writer(_Echo())

    def rows():
        yield writer.writerow([label for _, label in CSV_COLUMNS])
        for entry in entries.iterator(chunk_size=2000):
            yield writer.writerow([_csv_cell(getattr(entry, field)) for field, _ in CSV_COLUMNS])

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="audit-log-{timezone.now():%Y%m%d-%H%M%S}.csv"'
    return response


@login_required
def audit_log_list(request):
    require_permission(request.user, "audit_log.manage", "view the audit log")

    entries, filters = _filtered_entries(request)
    query, method, actor, status_bucket = (
        filters["query"], filters["method"], filters["actor"], filters["status_bucket"],
    )

    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
    except ValueError:
        page_size = DEFAULT_PAGE_SIZE
    if page_size not in PAGE_SIZE_CHOICES:
        page_size = DEFAULT_PAGE_SIZE

    page_obj = Paginator(entries, page_size).get_page(request.GET.get("page"))
    page_range = [
        p if isinstance(p, int) else None
        for p in page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    ]

    method_choices = list(AuditLogEntry.objects.order_by().values_list("method", flat=True).distinct())
    actor_choices = sorted(
        AuditLogEntry.objects.exclude(actor_username="").order_by()
        .values_list("actor_username", flat=True).distinct()
    )

    carry_params = request.GET.copy()
    carry_params.pop("page", None)
    carry_querystring = carry_params.urlencode()

    return render(
        request, "audit/list.html",
        {
            "page_obj": page_obj,
            "page_range": page_range,
            "query": query,
            "method": method,
            "actor": actor,
            "status_bucket": status_bucket,
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
            "page_size": page_size,
            "page_size_choices": PAGE_SIZE_CHOICES,
            "method_choices": method_choices,
            "actor_choices": actor_choices,
            "status_buckets": list(STATUS_BUCKETS.keys()),
            "carry_querystring": carry_querystring,
            "retention_days": settings.AUDIT_LOG_RETENTION_DAYS,
            "breadcrumbs": [{"label": "Audit Log"}],
        },
    )


@login_required
def purge_view(request):
    require_permission(request.user, "audit_log.manage", "purge the audit log")

    if request.method == "POST":
        counts = purge_older_than()
        messages.success(
            request,
            f"Purged {counts['audit_log']} audit log entr"
            f"{'y' if counts['audit_log'] == 1 else 'ies'} and "
            f"{counts['login_attempts']} login attempt(s) older than "
            f"{settings.AUDIT_LOG_RETENTION_DAYS} days.",
        )

    return redirect(reverse("audit:list"))


@login_required
def purge_all_confirm(request):
    require_permission(request.user, "audit_log.manage", "clear the audit log")

    return render(
        request, "audit/purge_all_confirm.html",
        {"confirm_phrase": CLEAR_ALL_CONFIRM_PHRASE, "breadcrumbs": [{"label": "Audit Log", "url": reverse("audit:list")}, {"label": "Clear all logs"}]},
    )


@login_required
def purge_all_view(request):
    require_permission(request.user, "audit_log.manage", "clear the audit log")

    if request.method != "POST":
        return redirect(reverse("audit:purge_all_confirm"))

    if request.POST.get("confirm_phrase") != CLEAR_ALL_CONFIRM_PHRASE:
        messages.error(request, "Confirmation phrase didn't match — nothing was deleted.")
        return redirect(reverse("audit:purge_all_confirm"))

    # A full purge is the one action that erases audit history outright
    # (an insider covering their tracks could otherwise just clear the log),
    # so it's the one action here that isn't left to a single permission
    # holder — a second, genuinely different Superadmin has to authenticate
    # to it too.
    approver_username = request.POST.get("approver_username", "").strip()
    approver_password = request.POST.get("approver_password", "")
    approver = authenticate(request, username=approver_username, password=approver_password)
    if approver is None:
        messages.error(request, "Second approver's credentials didn't check out — nothing was deleted.")
        return redirect(reverse("audit:purge_all_confirm"))
    if not approver.is_superadmin_role or not approver.is_active:
        messages.error(request, "The second approver must be an active Superadmin — nothing was deleted.")
        return redirect(reverse("audit:purge_all_confirm"))
    if approver.pk == request.user.pk:
        messages.error(
            request, "The second approver must be a different Superadmin from you — nothing was deleted."
        )
        return redirect(reverse("audit:purge_all_confirm"))

    counts = purge_all()
    messages.success(
        request,
        f"Cleared all audit log entries — deleted {counts['audit_log']} audit log entr"
        f"{'y' if counts['audit_log'] == 1 else 'ies'} and {counts['login_attempts']} login attempt(s). "
        f"Approved by {approver.username}.",
    )
    return redirect(reverse("audit:list"))
