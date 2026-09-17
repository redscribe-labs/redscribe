#!/bin/sh
# Waits for a cert to exist (so nginx never fails to start just because
# the tailscale-cert-loop sidecar hasn't issued the first one yet — same
# handling whether that gap is seconds, as with the tailscale profile, or
# indefinite, as when a BYO cert simply hasn't been dropped into ./certs
# yet), then runs nginx in the foreground and reloads it whenever the
# cert file's content actually changes underneath it — nginx caches
# loaded certs in the worker process and never picks up a renewed file on
# its own without a reload (or restart).
set -e

# Re-run the ${NGINX_SERVER_NAME} substitution ourselves rather than
# relying solely on the base image's own docker-entrypoint.d/20-envsubst-
# on-templates.sh having already run before we get here — on a fresh
# `docker compose up -d` (container Created, not Restarted) that step
# was observed to sometimes lose the race and leave the image's stock
# conf.d/default.conf in place instead. Idempotent and cheap, so doing it
# again here removes the dependency on that ordering entirely. Restricted
# to exactly this one variable name (same technique the base script
# itself uses, just scoped explicitly) so nginx's own runtime variables
# below ($host, $remote_addr, ...) are never touched.
envsubst '${NGINX_SERVER_NAME}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

CERT_FILE="/etc/nginx/certs/fullchain.pem"
KEY_FILE="/etc/nginx/certs/privkey.pem"

echo "Waiting for TLS certificate at $CERT_FILE ..."
while [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; do
    sleep 2
done
echo "Certificate found, starting nginx."

# This container runs with network_mode: host (see docker-compose.yml), so
# /proc/net/tcp here is the HOST's socket table, not a container-private
# one — a listener found here really is something else on the host, not
# noise from another container. Checked ourselves, before even trying to
# bind, because nginx's own failure mode for this (retry a few times over
# ~2s, then exit — logged as a bare "bind() ... Address in use") reads
# like a generic port conflict with no pointer to the actual cause. The
# most common real cause on this project's Method 1 (Tailscale) deploy:
# a leftover `tailscale funnel`/`tailscale serve` mapping from a previous
# session. That state lives in tailscaled on the HOST, not in any
# container or volume, so it survives `docker compose down`, container
# removal, even wiping every container and starting fresh — nothing
# short of an explicit `tailscale serve reset` (or reboot/tailscaled
# restart) clears it. 0x1BB/0x50 = 443/80 in the hex port field
# /proc/net/tcp uses; state 0A = LISTEN.
port_already_bound() {
    awk -v port="$1" '
        NR > 1 {
            split($2, a, ":")
            if (a[2] == port && $4 == "0A") found = 1
        }
        END { exit !found }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

if port_already_bound 01BB || port_already_bound 0050; then
    echo "==================================================================="
    echo "Port 80 or 443 is already bound on this host — nginx won't be able"
    echo "to start. This most often means tailscaled itself is holding the"
    echo "port because of a leftover 'tailscale funnel'/'tailscale serve'"
    echo "config from an earlier session (see README's Funnel section) —"
    echo "that state lives on the host, not in Docker, so nuking containers"
    echo "or volumes never clears it. On the HOST (not in this container):"
    echo "    tailscale serve status   # look for '(Funnel on)' / a tcp mapping"
    echo "    tailscale serve reset    # clears it, if that's what you find"
    echo "If that's not it, find whatever else owns the port with"
    echo "'sudo ss -tlnp | grep :443' on the host."
    echo "==================================================================="
fi

nginx -g "daemon off;" &
NGINX_PID=$!

LAST_HASH=""
while kill -0 "$NGINX_PID" 2>/dev/null; do
    sleep 3600
    CUR_HASH=$(md5sum "$CERT_FILE" 2>/dev/null | awk '{print $1}')
    if [ -n "$LAST_HASH" ] && [ -n "$CUR_HASH" ] && [ "$CUR_HASH" != "$LAST_HASH" ]; then
        echo "Certificate changed, reloading nginx..."
        nginx -s reload
    fi
    LAST_HASH="$CUR_HASH"
done
wait "$NGINX_PID"
