from contextlib import contextmanager
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import ReportJob, ReportSettings

STALE_JOB_TIMEOUT_SECONDS = 600


def _sweep_stale_jobs():
    cutoff = timezone.now() - timedelta(seconds=STALE_JOB_TIMEOUT_SECONDS)
    ReportJob.objects.filter(started_at__lt=cutoff).delete()


@contextmanager
def report_job_slot(engagement, fmt: str):
    ReportSettings.get_solo()

    with transaction.atomic():
        settings_obj = ReportSettings.objects.select_for_update().get(pk=1)
        _sweep_stale_jobs()
        active_count = ReportJob.objects.count()
        job = None
        if active_count < settings_obj.max_concurrent_report_jobs:
            job = ReportJob.objects.create(engagement=engagement, fmt=fmt)

    if job is None:
        yield False
        return

    try:
        yield True
    finally:
        job.delete()
