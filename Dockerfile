FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The PostgreSQL 18 client (pg_dump/pg_restore for apps.backup) isn't in
# Debian trixie, which only ships v17 — so it comes from PGDG, the
# PostgreSQL project's own apt repo. curl + gnupg are pulled in only to
# fetch/verify the repo key and are purged again in the same layer so they
# never reach the final image (which otherwise ships no HTTP client — even
# the healthcheck uses python urllib, see docker-compose.yml). ca-certificates
# is kept: allauth's OAuth token calls need it at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        # pg_dump/pg_restore for apps.backup — full-instance encrypted
        # backup/restore, Superadmin-only. v18 client: it dumps/restores both
        # v17 and v18 servers, so it keeps backups working while the server is
        # migrated 17 -> 18 (a v17 pg_dump refuses an 18 server outright).
        # Pulls libpq5 v18 from PGDG as a dependency — the library the
        # findings/reports paths also link against.
        postgresql-client-18 \
        # WeasyPrint (report PDF export) — text/graphics rendering via
        # Pango/Cairo.
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        # WeasyPrint uses HarfBuzz's subsetting API to embed only the glyphs
        # a report actually uses; without this it warns and falls back to
        # embedding whole fonts.
        libharfbuzz-subset0 \
        fonts-dejavu-core \
        shared-mime-info \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/staticfiles \
    && chown -R appuser /app \
    && chmod +x /app/entrypoint.sh
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# Shell form (via sh -c) so $GUNICORN_WORKERS — exported by entrypoint.sh,
# either from .env or auto-sized from nproc — is expanded at container
# startup, after entrypoint.sh has had a chance to set it.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS}"]
