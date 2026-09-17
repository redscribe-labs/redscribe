import uuid

import psycopg

from .pg import RestoreError, _connection_args, _db_settings, _pg_env, _run

SCRATCH_DB_PREFIX = "redscribe_restore_preview_"


def _admin_connect():
    db = _db_settings()
    return psycopg.connect(
        host=db["HOST"], port=db["PORT"], user=db["USER"], password=db["PASSWORD"],
        dbname="postgres", autocommit=True,
    )


def _fetch_accounts(dbname: str) -> dict:
    db = _db_settings()
    with psycopg.connect(
        host=db["HOST"], port=db["PORT"], user=db["USER"], password=db["PASSWORD"], dbname=dbname,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT username, is_active FROM accounts_user")
            return {username: is_active for username, is_active in cur.fetchall()}


class AccountImpact:
    def __init__(self, reactivated, newly_deactivated, disappearing, reappearing):
        self.reactivated = reactivated
        self.newly_deactivated = newly_deactivated
        self.disappearing = disappearing
        self.reappearing = reappearing

    @property
    def has_changes(self) -> bool:
        return any([self.reactivated, self.newly_deactivated, self.disappearing, self.reappearing])


def compute_account_impact(dump_bytes: bytes) -> AccountImpact:
    try:
        return _compute_account_impact(dump_bytes)
    except RestoreError:
        raise
    except psycopg.Error as exc:
        raise RestoreError(f"Couldn't compare accounts against the live database: {exc}")


def _compute_account_impact(dump_bytes: bytes) -> AccountImpact:
    scratch_db = f"{SCRATCH_DB_PREFIX}{uuid.uuid4().hex[:12]}"

    with _admin_connect() as conn:
        conn.execute(f'CREATE DATABASE "{scratch_db}"')

    try:
        result = _run(
            ["pg_restore", "--no-owner", "--no-privileges", *_connection_args(), "-d", scratch_db],
            input=dump_bytes, env=_pg_env(),
        )
        if result.returncode != 0:
            raise RestoreError(result.stderr.decode("utf-8", errors="replace")[:2000])

        backup_accounts = _fetch_accounts(scratch_db)
    finally:
        with _admin_connect() as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{scratch_db}" WITH (FORCE)')

    live_accounts = _fetch_accounts(_db_settings()["NAME"])

    reactivated, newly_deactivated, disappearing = [], [], []
    for username, live_active in live_accounts.items():
        backup_active = backup_accounts.get(username)
        if backup_active is None:
            disappearing.append(username)
        elif live_active and not backup_active:
            newly_deactivated.append(username)
        elif not live_active and backup_active:
            reactivated.append(username)

    reappearing = [u for u in backup_accounts if u not in live_accounts]

    return AccountImpact(
        reactivated=sorted(reactivated),
        newly_deactivated=sorted(newly_deactivated),
        disappearing=sorted(disappearing),
        reappearing=sorted(reappearing),
    )
