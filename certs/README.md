# TLS certificate directory

nginx (see `../nginx/templates/default.conf.template`) always reads exactly
two files from here, regardless of where they came from:

```
certs/fullchain.pem
certs/privkey.pem
```

## Tailscale (automated)

```
docker compose --profile tailscale up -d
```

The `cert-renew` service issues and keeps renewing these files automatically
via the host's `tailscaled` — nothing to do manually beyond setting
`NGINX_SERVER_NAME` in `.env` to your tailnet hostname (e.g.
`redscribe.your-tailnet.ts.net`). It runs as root inside its container, so
it needs no `tailscale set --operator=` step on the host and no `./certs`
ownership fix-up on a fresh clone — root is always trusted for
`tailscale cert` and bypasses host file-permission checks either way.

> **Your tailnet hostname becomes publicly visible.** `tailscale cert`
> issues a real publicly-trusted certificate (via Let's Encrypt), and every
> certificate issued this way is recorded in public Certificate
> Transparency logs — permanently and searchably. So while this hostname
> only resolves and routes inside your tailnet (nobody outside it can
> reach the app), the hostname's *existence* — `redscribe.your-tailnet.ts.net`
> — is not a secret once a cert is issued for it. **The service itself
> stays private regardless** — CT logs only leak the name, not access;
> nothing is actually reachable from the public internet unless you
> separately configure a [Tailscale
> Funnel](https://tailscale.com/kb/1223/funnel), which this project does
> not set up for you.

## Bring your own cert

Don't use the `tailscale` profile. Instead, drop your own certificate here
under those exact two filenames — e.g. from Let's Encrypt/certbot, a
corporate CA, or anywhere else:

```
cp /etc/letsencrypt/live/yourdomain/fullchain.pem certs/fullchain.pem
cp /etc/letsencrypt/live/yourdomain/privkey.pem   certs/privkey.pem
docker compose up -d
```

nginx (see `nginx/watch-certs.sh`) waits for both files to exist before it
starts, and reloads automatically (no restart needed) whenever it notices
`fullchain.pem`'s content change — so renewing your own cert in place (e.g.
via your own certbot timer) is picked up within the hour without you having
to touch this stack at all.

Both files are gitignored (`*.pem`/`*.crt`/`*.key`) — never commit key
material.
