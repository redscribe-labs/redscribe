import os
import subprocess

from django.conf import settings

DUMP_MAGIC = b"PGDMP"


class RestoreError(Exception):
    pass


def _db_settings() -> dict:
    return settings.DATABASES["default"]


def _pg_env() -> dict:
    return {**os.environ, "PGPASSWORD": _db_settings()["PASSWORD"]}


def _connection_args() -> list[str]:
    db = _db_settings()
    return ["-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"]]


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, timeout=600, **kwargs)
    except subprocess.TimeoutExpired:
        raise RestoreError(f"{args[0]} timed out after 600s.")
    except OSError as exc:
        raise RestoreError(f"Couldn't run {args[0]}: {exc}")


def dump_database() -> bytes:
    db = _db_settings()
    result = _run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", *_connection_args(), db["NAME"]],
        env=_pg_env(),
    )
    if result.returncode != 0:
        raise RestoreError(result.stderr.decode("utf-8", errors="replace")[:2000])
    return result.stdout


def restore_database(dump_bytes: bytes) -> None:
    if not dump_bytes.startswith(DUMP_MAGIC):
        raise RestoreError("Decrypted content isn't a valid Postgres custom-format dump.")

    from django.db import connections
    connections.close_all()

    db = _db_settings()

    reset = _run(
        ["psql", *_connection_args(), "-d", db["NAME"], "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
        env=_pg_env(),
    )
    if reset.returncode != 0:
        raise RestoreError(reset.stderr.decode("utf-8", errors="replace")[:2000])

    result = _run(
        [
            "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
            *_connection_args(), "-d", db["NAME"],
        ],
        input=dump_bytes, env=_pg_env(),
    )
    if result.returncode != 0:
        raise RestoreError(result.stderr.decode("utf-8", errors="replace")[:2000])
