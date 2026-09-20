from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect

from apps.crypto.access import engagement_access_required
from apps.crypto.services import encrypt_bytes, record_aad

from . import retest
from .forms import RetestRecordForm
from .models import Finding


@engagement_access_required
def retest_record_create(request, engagement_id, pk):
    finding = get_object_or_404(Finding, pk=pk, engagement=request.engagement)
    if not retest.can_log_retest_result(request.user, finding):
        raise PermissionDenied(
            "Retest results can only be logged while the engagement is Awaiting Remediation Test "
            "or in Remediation Test."
        )

    if request.method == "POST":
        form = RetestRecordForm(request.POST)
        if form.is_valid():
            notes = form.cleaned_data["notes"]
            record = retest.log_retest_result(
                finding, status=form.cleaned_data["status"], notes_ciphertext=None,
                tested_by=request.user,
            )
            if notes:
                record.notes_ciphertext = encrypt_bytes(
                    notes.encode("utf-8"), request.project_key,
                    associated_data=record_aad("retestrecord", record.pk, "notes"),
                )
                record.save(update_fields=["notes_ciphertext"])
            messages.success(request, "Retest result logged.")
        else:
            messages.error(request, "Retest result couldn't be saved.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=pk)
