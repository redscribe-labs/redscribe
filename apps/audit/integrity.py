from django.db import connection, transaction

from .models import AuditLogEntry

GENESIS_HASH = "0" * 64

_CHAIN_LOCK_KEY = 918_273_645


def compute_entry_hash(entry: AuditLogEntry, prev_hash: str) -> str:
    import hashlib
    import hmac

    from django.conf import settings

    canonical = "|".join(
        "" if value is None else str(value)
        for value in [
            prev_hash,
            entry.pk,
            entry.created_at.isoformat(),
            entry.actor_id,
            entry.actor_username,
            entry.actor_role,
            entry.action,
            entry.method,
            entry.path,
            entry.status_code,
            entry.engagement_id,
            entry.object_ref,
            entry.ip_address,
            entry.query_string,
            entry.referer,
            entry.user_agent,
            entry.duration_ms,
        ]
    )
    return hmac.new(settings.SECRET_KEY.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def append_with_chain(**fields) -> AuditLogEntry:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_CHAIN_LOCK_KEY])

        last = AuditLogEntry.objects.order_by("-pk").first()
        prev_hash = last.entry_hash if last and last.entry_hash else GENESIS_HASH

        entry = AuditLogEntry.objects.create(**fields)
        entry.entry_hash = compute_entry_hash(entry, prev_hash)
        entry.save(update_fields=["entry_hash"])
        return entry
