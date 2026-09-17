import re
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.accounts.models import LoginAttempt

from .models import AuditLogEntry

_YEAR_PARTITION_RE = re.compile(r"^audit_auditlogentry_(\d{4})$")


def retention_cutoff(days=None):
    days = settings.AUDIT_LOG_RETENTION_DAYS if days is None else days
    return timezone.now() - timedelta(days=days)


def _year_partitions() -> dict[int, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT child.relname
            FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_class child ON pg_inherits.inhrelid = child.oid
            WHERE parent.relname = 'audit_auditlogentry'
            """
        )
        names = [row[0] for row in cursor.fetchall()]

    partitions = {}
    for name in names:
        match = _YEAR_PARTITION_RE.match(name)
        if match:
            partitions[int(match.group(1))] = name
    return partitions


def _drop_fully_expired_year_partitions(cutoff) -> int:
    deleted = 0
    with connection.cursor() as cursor:
        for year, partition in _year_partitions().items():
            partition_upper = timezone.datetime(year + 1, 1, 1, tzinfo=timezone.get_default_timezone())
            if partition_upper > cutoff:
                continue
            cursor.execute(f"SELECT count(*) FROM {partition}")
            deleted += cursor.fetchone()[0]
            cursor.execute(f"ALTER TABLE audit_auditlogentry DETACH PARTITION {partition}")
            cursor.execute(f"DROP TABLE {partition}")
    return deleted


def purge_older_than(days=None) -> dict:
    cutoff = retention_cutoff(days)
    partition_deleted = _drop_fully_expired_year_partitions(cutoff)
    row_deleted, _ = AuditLogEntry.objects.filter(created_at__lt=cutoff).delete()
    login_deleted, _ = LoginAttempt.objects.filter(created_at__lt=cutoff).delete()
    return {"audit_log": partition_deleted + row_deleted, "login_attempts": login_deleted}


def count_older_than(days=None) -> dict:
    cutoff = retention_cutoff(days)
    return {
        "audit_log": AuditLogEntry.objects.filter(created_at__lt=cutoff).count(),
        "login_attempts": LoginAttempt.objects.filter(created_at__lt=cutoff).count(),
    }


def purge_all() -> dict:
    audit_deleted, _ = AuditLogEntry.objects.all().delete()
    login_deleted, _ = LoginAttempt.objects.all().delete()
    return {"audit_log": audit_deleted, "login_attempts": login_deleted}
