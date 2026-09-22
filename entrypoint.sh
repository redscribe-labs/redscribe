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
# GUNICORN_WORKERS explicitly in .env.
#
# Deliberately NOT `nproc` here: it reports the number of cores the
# scheduler could put this process on (sched_getaffinity), which a
# Compose `cpus:` limit never changes -- that key sets a CFS quota
# (time-sliced throttling), not a cpuset restriction, so `nproc` still
# reports the HOST's full core count even under a small `WEB_CPUS`
# share. Confirmed empirically: `WEB_CPUS=1` on a 2-core host still gave
# `nproc` == 2, over-provisioning to 5 workers instead of the 3 that
# quota can actually run. Read the cgroup's own quota/period directly
# instead, so this tracks the real limit regardless of host size.
cpu_count() {
    if [ -r /sys/fs/cgroup/cpu.max ]; then
        # cgroup v2: "<quota> <period>", or "max <period>" if unlimited.
        set -- $(cat /sys/fs/cgroup/cpu.max)
        quota=$1; period=$2
    elif [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_period_us ]; then
        # cgroup v1: quota -1 means unlimited.
        quota=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)
        period=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)
        [ "$quota" = "-1" ] && quota="max"
    else
        quota="max"
    fi
    if [ "$quota" = "max" ] || [ -z "$quota" ] || [ -z "$period" ]; then
        nproc
    else
        # Ceiling division so a fractional quota (e.g. 0.5 CPUs) still
        # sizes for at least 1 whole core's worth of workers, never 0.
        echo $(( (quota + period - 1) / period ))
    fi
}

if [ -z "$GUNICORN_WORKERS" ]; then
    export GUNICORN_WORKERS=$(( $(cpu_count) * 2 + 1 ))
fi

exec "$@"
