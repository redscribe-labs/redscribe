# Speeds up the icontains searches in apps.audit.views.audit_log_list and
# AuditLogEntryAdmin.search_fields, which do substring matching that a
# plain B-tree index can't accelerate. Deliberately ordered before the
# partitioning migration (0005): CREATE INDEX CONCURRENTLY isn't a single
# atomic operation against a partitioned parent table the way it is
# against a plain table, so these are added while AuditLogEntry is still
# a plain heap and carried over as part of 0005's index-recreation step.
#
# atomic = False is required — CREATE INDEX CONCURRENTLY cannot run
# inside a transaction.
from django.db import migrations

TRIGRAM_FIELDS = [
    "actor_username",
    "action",
    "path",
    "object_ref",
    "ip_address",
    "user_agent",
    "referer",
    "engagement_id",
]


def _index_name(field: str) -> str:
    return f"audit_auditlogentry_{field}_trgm"


def _index_expr(field: str) -> str:
    # ip_address is a GenericIPAddressField -> Postgres `inet`, which
    # gin_trgm_ops doesn't accept directly (it operates on text). Every
    # other field here is already a plain char/text column.
    return f"(ip_address::text)" if field == "ip_address" else field


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('audit', '0003_auditlogentry_entry_hash'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        *[
            migrations.RunSQL(
                sql=(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_index_name(field)} "
                    f"ON audit_auditlogentry USING GIN ({_index_expr(field)} gin_trgm_ops);"
                ),
                reverse_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {_index_name(field)};",
            )
            for field in TRIGRAM_FIELDS
        ],
    ]
