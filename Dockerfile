FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        # pg_dump/pg_restore for apps.backup — full-instance encrypted
        # backup/restore, Superadmin-only. libpq5 above is just the client
        # library findings/reports already need; this adds the actual
        # dump/restore binaries.
        postgresql-client \
        # WeasyPrint (report PDF export) — text/graphics rendering via
        # Pango/Cairo.
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu-core \
        shared-mime-info \
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
