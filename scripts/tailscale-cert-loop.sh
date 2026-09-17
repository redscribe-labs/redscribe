#!/bin/sh
# Runs inside the `cert-renew` compose service (profile: tailscale) — a
# thin tailscale-CLI-only container talking to the *host's* tailscaled
# over its bind-mounted unix socket (no separate Tailscale device/identity
# needed; runs as the image's default root user, which tailscaled always
# trusts for privileged operations like `tailscale cert`, so no
# `tailscale set --operator=` step is needed on the host). `tailscale
# cert` is safe to call repeatedly — it's a no-op renewal until the cert
# is within --min-validity of expiring.
set -e
: "${TS_CERT_DOMAIN:?TS_CERT_DOMAIN must be set (see .env's NGINX_SERVER_NAME)}"

# This project's setup wants nginx (see nginx/watch-certs.sh) binding
# host port 443 directly with the cert issued below — not proxied
# through `tailscale serve`/Funnel. That config lives in tailscaled on
# the HOST, not in any container, so it survives `docker compose down`
# and even a full container/volume wipe; a leftover mapping from an
# earlier session (e.g. someone tried Funnel before switching to this
# compose-managed nginx) silently steals port 443 and makes nginx's own
# bind() fail with a bare "Address in use" that gives no hint why. Reset
# is idempotent — a no-op if there's no serve config — so doing it once
# on every cert-renew startup keeps a fresh host from hitting this.
tailscale --socket=/var/run/tailscale/tailscaled.sock serve reset || true

while true; do
    tailscale --socket=/var/run/tailscale/tailscaled.sock cert \
        --cert-file=/certs/fullchain.pem \
        --key-file=/certs/privkey.pem \
        --min-validity=720h \
        "$TS_CERT_DOMAIN"
    sleep 21600  # 6h — cheap to check often, tailscale cert no-ops if still valid
done
