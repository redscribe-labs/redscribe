#!/bin/sh
set -e

# .env.example ships DJANGO_SETTINGS_MODULE=config.settings.dev on purpose
# (see README's "Dev vs. prod settings") — fine for local/private-network
# trial use, but a real deployment run through this same docker-compose
# path needs config.settings.prod for HTTPS enforcement/secure cookies/HSTS.
# Loud reminder so that choice is never silently left on the dev default.
case "$DJANGO_SETTINGS_MODULE" in
    *.dev|"")
        echo "============================================================"
        echo "WARNING: DJANGO_SETTINGS_MODULE is '$DJANGO_SETTINGS_MODULE'"
        echo "(dev settings, or unset). This disables HTTPS redirect,"
        echo "secure cookies, and HSTS. Fine for local/private-network"
        echo "trial use only — for a real deployment, set"
        echo "  DJANGO_SETTINGS_MODULE=config.settings.prod"
        echo "in .env. See README.md's 'Dev vs. prod settings' section."
        echo "============================================================"
        ;;
esac

# config.settings.prod hard-fails at import time if this is unset (see
# that module) — dev intentionally doesn't, so migrate/collectstatic still
# work on a brand new instance before the operator has generated one. This
# is just a loud reminder so it's not silently missing until the first
# attempt to create an engagement fails deep in a stack trace.
if [ -z "$REDSCRIBE_ROOT_KEY" ] && [ ! -f "${REDSCRIBE_ROOT_KEY_FILE:-/run/secrets/redscribe_root_key}" ]; then
    echo "============================================================"
    echo "WARNING: no root key found (REDSCRIBE_ROOT_KEY unset, no"
    echo "${REDSCRIBE_ROOT_KEY_FILE:-/run/secrets/redscribe_root_key} secret file)."
    echo "Encrypted fields (engagement data, findings, etc.) cannot be"
    echo "read or written until one is. Generate one with:"
    echo "  docker compose exec web python manage.py generate_root_key"
    echo "then put the output in ./secrets/root_key.txt and restart."
    echo "See README.md for the full first-run checklist."
    echo "============================================================"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Gunicorn defaults to a single sync worker if --workers isn't passed,
# which means a single-process app never uses more than one CPU core no
# matter how many the host actually has. Auto-size to the standard
# (2 * cores) + 1 gunicorn-recommended formula unless the operator set
# GUNICORN_WORKERS explicitly in .env. nproc reflects cgroup CPU limits
# when the container has any (e.g. `docker run --cpus`), not just the
# host's total core count.
if [ -z "$GUNICORN_WORKERS" ]; then
    export GUNICORN_WORKERS=$(( $(nproc) * 2 + 1 ))
fi

exec "$@"
