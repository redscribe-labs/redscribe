# RedScribe

**`0.1.0-alpha.1`** — self-hosted engagement, finding, checklist, and report
management for a small penetration testing team.

![version](https://img.shields.io/badge/version-0.1.0--alpha.1-blue)
![license](https://img.shields.io/badge/license-source--available-orange)
![CI](https://img.shields.io/badge/CI-test.yml-lightgrey)

[Documentation](https://redscribe-labs.github.io/redscribe-docs/) ·
[Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) ·
[Security Policy](.github/SECURITY.md) · [Changelog](CHANGELOG.md)

Django + HTMX + Tailwind, Postgres, per-engagement AES-256-GCM encryption
for sensitive fields. This is alpha software — not yet production-ready;
see "Alpha status" at the bottom of this file before relying on it for a
real engagement.

## License

RedScribe is **source-available**, not [OSI-approved open source](https://opensource.org/osd)
— the source is public and modifiable, but the license restricts
commercial use, which the Open Source Definition doesn't permit. That
puts it in the same category as Sentry's Functional Source License, n8n's
Sustainable Use License, Chatwoot's, and MariaDB's Business Source
License.

- **Free** for personal and community/noncommercial use, under the
  [PolyForm Noncommercial License 1.0.0](LICENSE).
- **Commercial use** (including running it at a for-profit consultancy)
  requires a [commercial license](COMMERCIAL-LICENSE.md), no feature
  differences from the free tier.

**Commercial use is free right now.** As a kickstart for the community, a
commercial license key costs nothing for the first year: email
`redscribe.maintainer@proton.me` for one. Priced tiers begin once RedScribe
has been proven at the scale real enterprise engagements demand.

Nothing in RedScribe is feature-gated either way. See
[`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md) for full terms and
pricing.

## Table of contents

- [License](#license)
- [Features](#features)
- [Requirements](#requirements)
  - [System requirements (sizing)](#system-requirements-sizing)
- [Installation](#installation)
  - [Why nginx uses host networking](#why-nginx-uses-host-networking)
  - [Common setup (all methods)](#common-setup-all-methods)
  - [Method 1: Docker Compose + Tailscale](#method-1-docker-compose--tailscale-recommended--fully-automated-https)
  - [Method 2: Docker Compose + your own TLS certificate](#method-2-docker-compose--your-own-tls-certificate)
  - [Method 3: Docker Compose, plain HTTP](#method-3-docker-compose-plain-http-localprivate-network-only)
  - [Method 4: Local development without Docker](#method-4-local-development-without-docker)
  - [First run (Methods 1–3)](#first-run-methods-13)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Audit log retention](#audit-log-retention)
  - [Account recovery](#account-recovery-lost-password--lost-mfa-device)
  - [Backup & Restore](#backup--restore)
- [Development](#development)
  - [Dev vs. prod settings](#dev-vs-prod-settings)
  - [Running the test suite](#running-the-test-suite)
- [Contributing](#contributing)
- [Versioning](#versioning)
- [Alpha status](#alpha-status)

## Features

See `CHANGELOG.md` for the full, dated history — this is a summary of
what's shipped as of `0.1.0-alpha.1`.

**Engagement & finding management**
- Engagement create/edit/archive lifecycle, membership, and a scope-change
  approval workflow.
- Findings with a draft → review → QA workflow, CVSS v3.1 and v4.0
  calculators, retest/remediation tracking, recurring-vulnerability
  detection, and per-field comment threads.
- A reusable vulnerability catalogue with its own draft → pending-QA →
  approved workflow: anyone can submit a draft, only an approved entry
  can be imported into a finding, and a snapshot of an entry's last
  approved content is kept — editing an approved entry re-queues it for
  QA without breaking an import someone else is about to make from the
  version that's actually been vetted. Plus a Superadmin-managed field
  visibility system to hide narrative sections (e.g. business impact,
  references) an org doesn't use — on both Findings and catalogue
  templates — without deleting any data already saved in them.
- Checklists: template create/edit with granular per-item CRUD (Team Lead
  and Superadmin), JSON/CSV bulk import and JSON export, and multiple
  independent checklist runs per engagement (e.g. OWASP WSTG against a
  web app alongside OWASP API Top 10 against its API, on the same
  engagement) — with sequential next/previous navigation between items,
  and a JSON export of a run's full testing data (objectives, results,
  linked findings, comments). A fresh instance ships with zero templates
  — nothing is seeded by default, so pick your own via import.
  `docs/checklist-templates/owasp-wstg.json` is a ready-to-import
  template covering the full official OWASP WSTG test list (each item's
  objectives + a link back to the official page) if you want that as a
  starting point.
- Scanner import: Nmap XML, Burp Suite XML, Nuclei JSON-lines.
- Cross-engagement trend reporting and global search.

**Reporting**
- A shared IR (intermediate representation) driving a live preview and
  Markdown / PDF / HTML exporters, so every format renders the same
  content — cover, document control, amendment history, disclaimers,
  table of contents, every body section, back matter.
- Word (.docx) export fills in a Report Profile's own uploaded `.docx`
  template — `{{ tag }}` placeholders for plain values, `{{p tag }}` for
  rich content (paragraphs, code blocks, images, tables), and a
  `{%p for finding in findings %}` loop for the repeating finding block —
  rather than generating a document from scratch. Rich content is styled
  using named Word styles from the uploaded template's own style catalog,
  mapped per content role on the profile's "Word (.docx)" tab. **Scope note:**
  DOCX export is meant as a strong starting point for the deliverable, not a
  guaranteed camera-ready final document — organizations vary widely in
  reporting conventions, and not every house style is something a
  general-purpose template-filling engine can fully anticipate. The expected
  workflow is to export the `.docx`, apply any final organization-specific
  touches by hand, then deliver. For most findings and observations, the
  admin-configurable dynamic content blocks (finding sections, observations,
  testing phases, custom text blocks) combined with a Report Profile's own
  appearance and styling controls (fonts, per-severity colors, style-role
  mapping) are enough to cover the report end to end without manual editing —
  the escape hatch exists for the remaining cases rather than as the default
  expectation.
- Self-hosted Google Fonts, per-severity table theming, PDF password
  encryption, and a concurrency limiter for report generation jobs.
- Hidden fields (per field visibility settings above) are omitted from
  every exported format, not just the app UI.

**Client Portal**
- External client-company users log in through the same login page as
  staff and see a deliberately minimal, read-only view: their own
  non-archived engagements and, within them, only findings that have
  cleared QA. Nothing else is actionable besides their own password and
  MFA.
- Client company and client-account management is restricted to
  Superadmin/Team Lead; a new engagement must be linked to an existing
  client company at creation. A Superadmin-only instance-wide toggle
  turns client login/access on or off without affecting that management
  surface.
- Automatic (non-actionable) view tracking lets staff see, on a finding's
  own page, whether and when the client actually looked at it.

**Security**
- Per-engagement AES-256-GCM encryption at rest for sensitive fields, with
  a single instance root key wrapping each engagement's own data key.
- Dynamic role/permission model (Role Management), TOTP MFA (required for
  every local account), an OAuth scaffold (Google/Microsoft, not wired to
  a live provider by default), and instance-wide feature flags.
- An append-only, hash-chained audit log covering every request (not just
  state-changing ones) and every login attempt, with a configurable
  retention/purge policy and a `verify_audit_log` command to detect
  tampering.
- Idle-timeout automatic logoff (separate from the fixed session cap), a
  single active session per user (a fresh login revokes any other one,
  timed to land only once MFA is actually satisfied where it's required),
  and an active email alert to every Superadmin the moment an account is
  locked out or rate-limited — not just a passive record.
- New accounts (staff and client-portal) set their own password via a
  single-use, 24-hour emailed link instead of an admin choosing it for
  them. All other notification emails (reviewer/QA assignment, review/QA
  outcomes, scope-change decisions) are deliberately generic — no client
  name or finding title in the subject or body — so a compromised mailbox
  doesn't expose which clients or vulnerabilities an account was working
  on; the in-app notification list stays fully detailed.
- HSTS, strong-cipher-only TLS termination, and `Cache-Control: no-store`
  on dynamic responses, enforced at the nginx layer.

**Administration**
- Superadmin-only permanent-delete on already-archived engagements — the
  one deliberate exception to the archive-not-delete, append-only-audit
  design, for data-retention purge.
- Server-side-only encrypted full-instance backup/restore (`pg_dump`/
  `pg_restore`, password-based AES-256-GCM envelope) — no web UI, by
  design. Restore reports exactly which accounts would be reactivated or
  removed before touching the live database, so an account change made
  after the backup was taken can't be silently missed.
- Deployment: Docker Compose with an nginx reverse proxy, automated
  Tailscale TLS cert issuance/renewal (or bring-your-own-cert), and an
  auto-sized gunicorn worker count.

## Requirements

- **Docker** and **Docker Compose** (Methods 1–3 — the normal way to run
  this).
- For Method 4 (local development without Docker): **Python 3** (for a
  virtualenv) and a local **Postgres** (or just the `db` service from
  Docker Compose, as shown below).
- **Node.js/npm**, only if you need to rebuild the frontend asset bundles
  (Tiptap editor, password-strength meter, Tailwind CSS) after touching
  their sources — not a runtime dependency of the deployed app either way.
  See `BUILD.md`.
- If using Method 1: a host already joined to a
  [Tailscale](https://tailscale.com) tailnet with MagicDNS + HTTPS certs
  enabled.

### System requirements (sizing)

Sized by **concurrently active users**, not total registered accounts —
almost every request here is a fast, DB-backed read/write; the one thing
that blocks a full gunicorn worker for its duration is report export
(WeasyPrint PDF / DOCX assembly). "Recommended" below matches gunicorn's
`(2 × cores) + 1` worker formula (see [CPU / worker
count](#cpu--worker-count)) and the default `max_concurrent_report_jobs`
limiter; "Minimum" is the same box a tier down — it boots and holds up,
without headroom to spare. These are estimates from the app's own
concurrency model, not a load test — watch real report-export duration on
your largest engagement before committing to a tier.

| Tier | Concurrently active · registered accounts | vCPU (min → rec.) | RAM (min → rec.) | Gunicorn workers (rec.) | Disk | Report job slots |
|---|---|---|---|---|---|---|
| Solo | 1 user | 1 | 1 → 2 GB | 3 | 10 GB+ | 1 |
| Pilot | ≤5 · ≤10 | 1 → 2 | 2 → 4 GB | 5 | 20 GB | 2 (default) |
| Small firm | 10–15 · 10–30 | 2 → 4 | 4 → 8 GB | 9 | 40–50 GB | 2 (default) |
| Mid-size firm | 25–40 · 30–80 | 4 → 8 | 8 → 16 GB | 17 | 100 GB+ | 3–4 |
| Larger firm | 50+ · 80–150+ | 8 → 16 | 16 → 32 GB | 33 | 200 GB+ | 4–6, with caution |

Runs fine on a **1 vCPU / 1 GB** box for a single person kicking the tires
— below even the Solo row above — but that's a floor to try it out on, not
a comfortable size once a second person or a report export joins in.

Past "Larger firm," stop scaling the box: split Postgres onto its own
host and add a task queue (e.g. Redis + Celery/RQ) so report exports stop
competing with ordinary browsing for a gunicorn worker — see
[Development](#development) for the single-box concurrency model this
sizing is derived from.

**What shifts these numbers:**
- **RAM before CPU.** WeasyPrint's rendering engine spikes hardest on
  image-heavy reports — bias a tier's RAM up before its vCPU if findings
  carry a lot of screenshots.
- **Shared host.** These figures assume `web` + Postgres on one box, as
  shipped. Splitting the database onto its own host frees up headroom on
  both sides independently.
- **Disk growth** is driven by encrypted evidence blobs and backup
  retention, not schema size.
- **Per-engagement ceiling.** At most two people ever contend for one
  engagement's data, by design — so total accounts and concurrent load
  scale independently of write-conflict risk.

## Installation

Four ways to run this, in order of how much TLS setup they need. All of
them share the same "First run" finishing steps (root key + first
Superadmin) at the end of this section.

### Why nginx uses host networking

`nginx`'s service in `docker-compose.yml` runs with `network_mode: host`
rather than a `ports: - "80:80"` mapping, so it binds the host's ports
80/443 directly instead of going through Docker's own port-forwarding.
This matters for the app's login-lockout and audit logging, which both
record the client IP: on a default Docker install, a published-port
mapping is relayed through a userspace `docker-proxy` process that
substitutes its own address as the source for every connection, so
without this, nginx (and everything downstream) would see a
Docker-internal address instead of the real client IP for *every*
request — a host-level Docker daemon quirk that would otherwise need
re-fixing on every machine this gets deployed to. Host networking avoids
it entirely, with nothing to configure per-host — this is checked into
the repo and applies wherever it's deployed.

One case this doesn't (and can't) change: a request that originates
*from the machine running Docker itself* (e.g. testing via `localhost` or
that machine's own LAN/Tailscale address from a browser/curl running on
it) will still show `127.0.0.1` as the source rather than a real client
IP — there's no "real" external client in that case. To verify client IPs
are being recorded correctly, test from a genuinely different device.

### Common setup (all methods)

Copy the env template and generate its secrets first.

```
cp .env.example .env
```

```
# Django's session/CSRF signing key — any random 50-char string works
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50)))"

# Set POSTGRES_PASSWORD to something of your choosing.
```

`REDSCRIBE_ROOT_KEY` (the instance's master key — every engagement's
per-project data key is wrapped with this) needs the app's own generator,
so it's created in "First run" below, not here.

### Method 1: Docker Compose + Tailscale (recommended — fully automated HTTPS)

Best fit if the host is already on a [Tailscale](https://tailscale.com)
tailnet with MagicDNS + HTTPS certs enabled — no separate cert management,
no host cron, no manual renewal ever.

1. In `.env`, set `NGINX_SERVER_NAME=<your-machine>.<tailnet>.ts.net` (find
   it with `tailscale status --self --json`, field `DNSName`) and add the
   same hostname to `DJANGO_ALLOWED_HOSTS`.
2. Set `DJANGO_SETTINGS_MODULE=config.settings.prod` in `.env`.
3. ```
   docker compose --profile tailscale up -d --build
   ```

That's the whole thing. The `cert-renew` service issues the first cert and
keeps renewing it for as long as the stack runs (checks every 6h, no-ops
until near expiry); `nginx` waits for it to exist, then reloads
automatically whenever it changes. Continue at **First run** below.

> **Your tailnet hostname becomes publicly visible.** The cert
> `cert-renew` issues is a real, publicly-trusted certificate (via Let's
> Encrypt), and every certificate issued this way is logged permanently in
> public Certificate Transparency logs. So while the app itself stays
> reachable only from your tailnet (see below — that's unaffected), the
> hostname `<your-machine>.<tailnet>.ts.net` is discoverable by anyone
> watching CT logs the moment the first cert is issued. If that hostname
> itself is sensitive, don't use Method 1 — bring your own cert (Method 2)
> instead.

#### Exposing it beyond your tailnet with Tailscale Funnel (optional)

By default Method 1 is reachable only from devices on your tailnet. To make
it reachable from the public internet too, use [Tailscale
Funnel](https://tailscale.com/kb/1223/funnel) — but forward the connection
as **raw TCP**, not Funnel's default HTTPS-terminating mode. nginx already
terminates TLS itself with the cert `cert-renew` issued above; if Funnel
also terminates TLS and hands nginx decrypted HTTP, nginx's `listen 443
ssl;` rejects it outright with `400 The plain HTTP request was sent to
HTTPS port`.

```
tailscale funnel --bg --proxy-protocol=2 --tcp=443 443
```

`--tcp` (not `--tls-terminated-tcp`, despite that flag's name reading like
the right one — it actually means Tailscale itself strips the TLS before
forwarding) passes the encrypted bytes through untouched, so nginx sees the
real handshake. Confirm with `tailscale funnel status`; the mapping should
say plain `(Funnel on)`, not `(TLS-terminated TCP, Funnel on)`. Requires
Funnel enabled for your tailnet (same admin-console toggle as HTTPS
certs) — see the linked docs if `tailscale funnel` refuses to start.

`--proxy-protocol=2` matters just as much as `--tcp` itself: without it,
Funnel still relays the connection correctly, but nginx has no way to
recover the real visitor's IP — Funnel forwards over loopback, so every
request would otherwise show up in the audit log and login-lockout checks
as `127.0.0.1` instead of the actual client. nginx's config (see
`nginx/templates/default.conf.template`) already expects this flag —
`listen 127.0.0.1:443 ssl proxy_protocol;` is bound only to loopback (the
direct/tailnet listener on the same port is untouched by this) and reads
the client IP it conveys.

One side effect: since that loopback listener now requires every
connection landing on it to start with a PROXY protocol preamble,
`https://localhost/` or `https://127.0.0.1/` direct from the host itself
no longer works (the request looks like a malformed handshake to nginx)
— use the tailnet hostname instead, same as any other visitor would.

**Turning it back off:** `tailscale serve reset` on the host. This state
lives entirely in `tailscaled`, not in Docker, so it survives
`docker compose down`, removing containers/volumes, even wiping every
container and rebuilding from scratch — none of that touches it. Left in
place, it also causes a real conflict on the *next* `docker compose up`:
`tailscaled` is still holding port 443 for the Funnel forward, so `nginx`
(which needs that same port, see [Why nginx uses host
networking](#why-nginx-uses-host-networking)) fails to bind with `bind()
to 0.0.0.0:443 failed (98: Address in use)` and crash-loops. If you hit
that error, `tailscale serve status` on the host is the first thing to
check — nginx's own startup script also checks for this and prints a hint
pointing here.

### Method 2: Docker Compose + your own TLS certificate

For your own domain with a cert from anywhere else — Let's Encrypt/certbot,
a corporate CA, whatever you already run.

1. In `.env`, set `NGINX_SERVER_NAME=<your-domain>`, add it to
   `DJANGO_ALLOWED_HOSTS`, and set `DJANGO_SETTINGS_MODULE=config.settings.prod`.
2. Drop your certificate into place under exactly these two filenames
   (see `certs/README.md`):
   ```
   cp /path/to/your/fullchain.pem certs/fullchain.pem
   cp /path/to/your/privkey.pem   certs/privkey.pem
   ```
3. ```
   docker compose up -d --build
   ```
   (No `--profile tailscale` — that service only exists for Method 1.)

`nginx` waits for both files to exist before starting, and reloads
automatically (no restart needed) whenever it notices `fullchain.pem`'s
content change — so your own renewal process (e.g. a certbot timer) is
picked up within the hour without touching this stack at all. Continue at
**First run** below.

#### Moving a Method 1/2 deployment to a new machine

`certs/` is gitignored, so copying the project directory (rsync/scp/tar) to
a new host carries the *old* machine's `fullchain.pem`/`privkey.pem` along
with it — nginx doesn't check whether a cert's subject matches
`NGINX_SERVER_NAME`, it just serves whatever bytes are in those two files.
On the new machine, after updating `.env`'s `NGINX_SERVER_NAME`:

```
rm certs/fullchain.pem certs/privkey.pem
docker compose --profile tailscale up -d --build   # or `up -d --build` for BYO-cert (Method 2)
```

For Method 1, `cert-renew`'s `tailscale cert` call is a no-op renewal until
the file is near expiry — deleting the stale files first forces a real
reissue for the new domain instead of silently keeping the old one.

If nginx was already running when the new cert got written (e.g. you
deleted/reissued the cert without recreating the `nginx` container), it can
keep serving the stale cert it loaded at boot for up to an hour —
`watch-certs.sh` only checks the file's hash once an hour. Force it
immediately with:

```
docker compose exec nginx nginx -s reload
```

### Method 3: Docker Compose, plain HTTP (local/private network only)

No TLS at all — fine for trying this out locally or over a private
network you already trust, not for anything reachable beyond that.

```
docker compose up -d --build
```

Leave `DJANGO_SETTINGS_MODULE=config.settings.dev` (the `.env.example`
default) — `nginx` still starts alongside `web` but just idles waiting for
a certificate that will never arrive, harmlessly. Skip straight to
`http://localhost:8000/` (bound to loopback only, i.e. only reachable from
the host itself) instead of going through nginx. Continue at **First run**
below.

### Method 4: Local development without Docker

For working on the app itself without a container rebuild loop:

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db          # just the database
cp .env.example .env             # fill in secrets as above; POSTGRES_HOST=localhost
python manage.py migrate
python manage.py generate_root_key   # put the output in .env
python manage.py bootstrap_superadmin --username admin --email admin@example.com
python manage.py runserver
```

This already includes its own root key + Superadmin steps inline — skip
**First run** below, you're done. Rebuilding the frontend bundles after a
template/JS/CSS change is a separate step — see `BUILD.md`.

### First run (Methods 1–3)

1. **Build and start everything** (already done above per-method, repeated
   here for reference — the `web` container's entrypoint runs migrations
   and `collectstatic` automatically on every start):

   ```
   docker compose up -d --build          # or: docker compose --profile tailscale up -d --build
   ```

2. **Generate the instance root key** (do this once, before creating any
   engagements — losing it makes existing engagement data permanently
   unrecoverable):

   ```
   docker compose exec web python manage.py generate_root_key
   ```

   Copy the printed value into `secrets/root_key.txt` (see
   `secrets/README.md`), then restart so it picks it up:

   ```
   docker compose up -d web
   ```

3. **Create the first Superadmin.** Two ways to do this — pick one:

   - **Via the web UI (recommended):** visit `/setup/` on whichever
     address applies to your method (e.g. `https://<your-domain>/setup/`,
     or `http://localhost:8000/setup/` for Method 3) and fill in the form.
     This page only ever works before any Superadmin exists on the
     instance; once you've created one, it redirects to the login page
     instead.
   - **Via the CLI**, e.g. for scripted/automated deployments:

     ```
     docker compose exec web python manage.py bootstrap_superadmin --username admin --email admin@example.com
     ```

     You'll be prompted for a password (14+ characters).

   Either way, on first login you'll be walked through TOTP MFA enrollment
   (QR code + confirmation) — required for every local account, no way to
   skip it.

4. Visit `/login/` (or you're probably already there from step 3).

## Configuration

All configuration is via environment variables, normally set in `.env`
(copied from `.env.example` — see "Common setup" above). Cross-referenced
against `config/settings/base.py` / `config/settings/prod.py` where
`.env.example`'s own comments don't spell out the default or behavior.

**Django core**

| Variable | Purpose | Default |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Which settings module to run — `config.settings.dev` or `config.settings.prod` (see [Dev vs. prod settings](#dev-vs-prod-settings)). | `config.settings.dev` |
| `DJANGO_SECRET_KEY` | Session/CSRF signing key. Generate a random 50-char value (see "Common setup"); never reuse the placeholder. | `change-me-to-a-random-50-char-value` |
| `DJANGO_DEBUG` | Django debug mode — verbose error pages, no static file caching. Never enable in a real deployment. | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames Django will serve; must include whatever `NGINX_SERVER_NAME` is set to. | `localhost,127.0.0.1` |

**Reverse proxy / TLS**

| Variable | Purpose | Default |
|---|---|---|
| `NGINX_SERVER_NAME` | Your domain — tailnet hostname for Method 1, your own domain for Method 2. Leave unset for nginx's `_` catch-all default (Method 3). | *(unset)* |
| `GUNICORN_WORKERS` | Gunicorn worker process count. Leave unset to auto-size to `(2 * cpu cores) + 1` at container startup (see `entrypoint.sh`). | *(auto-sized)* |

**Database**

| Variable | Purpose | Default |
|---|---|---|
| `POSTGRES_DB` | Database name. | `redscribe` |
| `POSTGRES_USER` | Database user. | `redscribe` |
| `POSTGRES_PASSWORD` | Database password — set this to something of your own choosing. | `change-me` |
| `POSTGRES_HOST` | Database hostname — `db` under Docker Compose, `localhost` for Method 4. | `db` |
| `POSTGRES_PORT` | Database port. | `5432` |

**Encryption**

| Variable | Purpose | Default |
|---|---|---|
| `REDSCRIBE_ROOT_KEY` | Instance root key wrapping every engagement's own per-project data key. Generate with `python manage.py generate_root_key` (see "First run"); required in production — `config.settings.prod` refuses to start without it. Under Docker Compose this is mounted as a secret from `secrets/root_key.txt` instead (see `secrets/README.md`) and this var is left unset; only set it directly for a non-Docker/bare-metal run or CI. Never commit the real value. | *(unset)* |

**Authentication & rate limiting**

| Variable | Purpose | Default |
|---|---|---|
| `OAUTH_PROVIDER` | `"google"`, `"microsoft"`, or empty for local-auth-only (the scaffold isn't wired to a live provider by default). | *(empty)* |
| `SESSION_IDLE_TIMEOUT_SECONDS` | Signs a session out after this many seconds of no requests — HIPAA's automatic-logoff spec, distinct from the session's fixed 4-hour cap (`SESSION_COOKIE_AGE`, not separately configurable). | `1800` (30 min) |
| `LOCKOUT_THRESHOLD` | Failed login attempts before an account is locked out. | `5` |
| `LOCKOUT_DURATION_SECONDS` | How long a lockout lasts, in seconds. | `86400` (24h) |
| `SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit window for Superadmin-sensitive actions. | `60` |
| `SUPERADMIN_RATE_LIMIT_MAX_ATTEMPTS` | Max attempts allowed within that window. | `10` |
| `PWNED_PASSWORD_CHECK_ENABLED` | Checks new passwords against Have I Been Pwned's breach corpus (k-anonymity API — only a 5-char hash prefix ever leaves the instance). Set to `false` for air-gapped deployments with no outbound internet access. | `true` |

**Email** (password reset links + change notifications)

| Variable | Purpose | Default |
|---|---|---|
| `EMAIL_HOST` | SMTP host. Leave blank to use the console backend (emails printed to the app log) — fine for local/dev, not for production. | *(empty — console backend)* |
| `EMAIL_PORT` | SMTP port. | `587` |
| `EMAIL_HOST_USER` | SMTP username. | *(empty)* |
| `EMAIL_HOST_PASSWORD` | SMTP password. | *(empty)* |
| `EMAIL_USE_TLS` | Use TLS for the SMTP connection. | `true` |
| `DEFAULT_FROM_EMAIL` | From-address on outgoing mail. | `RedScribe <no-reply@redscribe.local>` |
| `PASSWORD_RESET_TIMEOUT_SECONDS` | How long a password reset link stays valid. | `3600` (1h) |

**Audit log**

| Variable | Purpose | Default |
|---|---|---|
| `AUDIT_LOG_RETENTION_DAYS` | How far back Audit Log entries are kept before eligible for purge. See [Audit log retention](#audit-log-retention) for details, including how the default compares to PCI DSS/NIST/CIS. | `2190` (6 years — HIPAA's general documentation-retention rule) |

**Backup**

| Variable | Purpose | Default |
|---|---|---|
| `BACKUP_DIR` | Where `create_backup` writes encrypted backups, server-side. See [Backup & Restore](#backup--restore). | `/app/backups` |
| `BACKUP_ENCRYPTION_PASSPHRASE` | Encrypts/decrypts backups. Required for `create_backup` to run unattended (host cron); `restore_backup` prompts interactively if this isn't set. Same trust level as this app's other `.env` secrets — never commit the real value. | *(empty)* |
| `BACKUP_RETENTION_DAYS` | How long `create_backup` keeps old backups in `BACKUP_DIR` before pruning them. | `30` |

## Usage

Once a Superadmin exists (see "First run"), log in at `/login/` — TOTP MFA
enrollment happens automatically on first login and can't be skipped.
From there, day-to-day work happens per-engagement (create one, add
members, run checklists, log findings, generate reports); instance-wide
operations live under a few dedicated areas:

- **Audit Log** (`/audit/`) — every request and login attempt, with a
  Superadmin-triggerable retention purge. See
  [Audit log retention](#audit-log-retention) below.
- **Backup & Restore** — server-side only, no web UI. See
  [Backup & Restore](#backup--restore) below.
- **Role Management** — the dynamic role/permission model referenced in
  [Features](#features).
- **Field Visibility** (`/field-visibility/`) — Superadmin-managed toggles
  for which narrative sections appear on Findings/catalogue templates.

### Audit log retention

Every request (GET/view traffic included, not just state-changing ones —
see `apps/audit/middleware.py`) is recorded in the Audit Log, along with
every login attempt. `AUDIT_LOG_RETENTION_DAYS` (default 2190 = 6 years,
matching HIPAA's general documentation-retention rule — see
`config/settings/base.py`'s comment for how that compares to PCI DSS/NIST/
CIS) controls how far back entries are kept; override it in `.env` per
your own compliance obligations.

Purging is never automatic — nothing in this project runs on a schedule
of its own — so wire it into your host's own cron for a self-maintaining
instance, e.g. daily at 3am:

```
0 3 * * * cd /path/to/redscribe && docker compose exec -T web python manage.py purge_audit_log
```

Add `--dry-run` to preview the delete count first, or `--days N` to purge
against a one-off window instead of the configured default. A Superadmin
can also trigger the same purge on demand from the "Purge entries older
than N days" button on the Audit Log page (`/audit/`) — same underlying
logic (`apps/audit/retention.py`) either way, and the purge action itself
is recorded in the audit trail like any other state-changing request.

**Tamper-evidence:** every entry's `entry_hash` is a SHA-256 of its own
fields chained onto the previous entry's hash (`apps/audit/integrity.py`)
— changing a stored row anywhere in the chain, including through direct
DB access rather than the app, invalidates every hash after it. Check the
whole chain at any time with:

```
docker compose exec web python manage.py verify_audit_log
```

The oldest surviving row can't be checked against a prior link — either
it's genuinely the first entry ever, or everything before it was
legitimately removed by `purge_audit_log`. The command reports that row
as an anchor, not a failure, and flags the first row after it (if any)
whose recomputed hash doesn't match what's stored.

### Account recovery (lost password / lost MFA device)

If a Superadmin (or any local account) loses their password, their TOTP
device, or both, there's no self-service recovery — fix it directly via
the CLI on the `web` container:

1. **Find the username**, if you don't already know it:

   ```
   docker compose exec web python manage.py shell -c "
   from apps.accounts.models import User
   for u in User.objects.filter(role__is_superadmin=True):
       print(u.username, u.email)
   "
   ```

2. **Reset the password** (interactive — prompts twice, input hidden):

   ```
   docker compose exec web python manage.py changepassword <username>
   ```

3. **If MFA access is also lost**, delete the confirmed TOTP device so the
   account is forced back through enrollment on next login:

   ```
   docker compose exec web python manage.py shell -c "
   from apps.accounts.models import User
   from django_otp.plugins.otp_totp.models import TOTPDevice
   u = User.objects.get(username='<username>')
   TOTPDevice.objects.filter(user=u).delete()
   "
   ```

Log in with the new password — with no confirmed TOTP device, the account
is routed straight to `mfa_enroll` (per `apps.accounts.middleware`) to set
up a fresh authenticator.

Never resort to wiping the database over a lost credential — that
destroys every engagement, finding, and report along with it. These
commands touch only the affected user's row.

### Backup & Restore

Server-side only, deliberately — this both exfiltrates (backup) and can
completely overwrite (restore) every engagement's data, so it's a
terminal-only operation for whoever already has that level of server
access, not a button reachable over HTTP. There's no web UI at all.

#### Creating backups

One-time setup — `create_backup` writes into `BACKUP_DIR`
(`/app/backups` inside the container), which needs a real host directory
behind it to survive a container recreation:

```
mkdir -p backups
```

(The `web` container runs as `appuser`, UID/GID 1000 — the directory
Docker just bind-mounted at `docker-compose.yml`'s `./backups:/app/backups`
needs to be writable by that UID. If your own host user isn't UID 1000,
`chown 1000:1000 backups` once.)

Set `BACKUP_ENCRYPTION_PASSPHRASE` in `.env` (required for unattended
runs — there's no one at a terminal to prompt), then run this daily via
the host's own cron, same pattern as `purge_audit_log`:

```
0 2 * * * cd /path/to/redscribe && docker compose exec -T web python manage.py create_backup
```

Each run writes one timestamped, encrypted file
(`redscribe-backup-<timestamp>.rsbk`) into `BACKUP_DIR` and prunes
anything older than `BACKUP_RETENTION_DAYS` (default 30 — a month of
daily backups). `--passphrase` overrides `BACKUP_ENCRYPTION_PASSPHRASE`
for a single run if you ever need that.

**`BACKUP_DIR` living on the same disk as the database it's backing up
is better than nothing, but doesn't protect against a whole-host
failure.** Sync it off-box yourself — `rsync`, `rclone`, whatever you
already use — this project doesn't build or assume any specific remote
target.

#### Restoring a backup

```
docker compose exec web python manage.py restore_backup /app/backups/redscribe-backup-<timestamp>.rsbk
```

(Prompts for the passphrase interactively; `--passphrase` skips that for
scripted disaster-recovery drills.)

**Before touching the live database**, this loads the backup into a
throwaway scratch database and compares its accounts against the ones
live right now, then prints exactly what would change — this is the
direct answer to the problem that motivated building it this way: a
whole-database restore silently undoes *any* account change made after
the backup was taken, including someone who was deactivated (e.g. left
the team) since then quietly regaining access, in a way that's easy to
miss if you're not specifically looking for it. You'll see one of four
things per affected account:

- **Reactivated** — inactive right now, active in the backup. The one
  that matters most: if this account was deliberately deactivated since
  the backup, restoring undoes that.
- **Newly deactivated** — the reverse (reactivated since the backup).
- **Disappearing** — created after the backup, so restoring removes it.
- **Reappearing** — deleted since the backup, so restoring brings it
  back.

Nothing here is automatic — you still have to look at the list and
decide, but it can no longer slip past unnoticed. Type `restore` at the
prompt to proceed, anything else to abort with zero changes made.
`--yes` skips the prompt (the report is still computed and printed
either way) for scripted DR — know what you're restoring before you
automate past this step.

Immediately before the actual `pg_restore` (which drops every table
first, then restores — not something a partial failure can be undone
from on its own), the command also takes its own encrypted snapshot of
whatever's live *right now* and writes it into `BACKUP_DIR` as
`redscribe-pre-restore-safety-<timestamp>.rsbk`, using the same
passphrase. If the restore then fails partway through, the database may
be left inconsistent — restore that safety file (same command, same
passphrase) to get back to exactly how things were the moment before you
ran this. Unlike the routine daily backups above, these aren't
auto-pruned by `BACKUP_RETENTION_DAYS` — clean them up yourself once
you've confirmed the restore actually worked.

Because this loads the backup up to three times (the scratch-database
comparison, the pre-restore safety snapshot, and the real restore),
expect it to take roughly three times as long as a raw `pg_restore`
would.

#### Upgrading, and rolling back a bad deploy or migration

`entrypoint.sh` runs `python manage.py migrate --noinput` unconditionally
on every container start — there's no dry-run step and no automatic
snapshot before it touches the schema. If a new migration (or the code
that shipped alongside it) turns out to be broken once it's live, the
backup/restore tooling above is your way back, but only if you took a
snapshot *before* upgrading. Make that step part of the upgrade, not
something you reach for after it's already gone wrong:

```
# 1. Snapshot the current, known-good state before pulling anything new.
docker compose exec -T web python manage.py create_backup

# 2. Pull/build the new version and restart as usual.
git pull
docker compose up -d --build

# 3. If something's broken: roll the code back first...
git checkout <previous-tag-or-commit>
docker compose up -d --build

# ...then restore the pre-upgrade snapshot from step 1 (path printed by
# create_backup, or look in BACKUP_DIR for the most recent
# redscribe-backup-<timestamp>.rsbk).
docker compose exec web python manage.py restore_backup /app/backups/redscribe-backup-<timestamp>.rsbk
```

Rolling the code back alone is sometimes enough (a bad release with no
migration in it) — restoring the database is only needed once a
migration has actually changed the schema in a way the old code can't
run against. Either way, having the pre-upgrade snapshot in hand before
you start means that decision is never made under pressure with nothing
to fall back on.

## Development

Working on the app itself typically means Method 4 above (no container
rebuild loop). If you touch the Tiptap editor bundle, the password
strength meter, or Tailwind classes, rebuild the frontend assets per
`BUILD.md` before committing.

### Dev vs. prod settings

`.env.example` defaults to `DJANGO_SETTINGS_MODULE=config.settings.dev`
(Installation Method 3) — no HTTPS-redirect behavior, works whether or not
anything is terminating TLS in front of it. `config.settings.prod`
(Methods 1 and 2) is for real deployment behind a TLS-terminating reverse
proxy: it sets `SECURE_PROXY_SSL_HEADER` to trust `X-Forwarded-Proto:
https` from that proxy, and hard-enforces HTTPS/HSTS/secure cookies once
that's set. Don't point `prod.py` at port 8000 directly without a proxy in
front setting that header — it force-redirects everything to HTTPS and
you'll get a redirect loop.

#### TLS cipher suite (nginx)

`nginx/templates/default.conf.template` restricts TLS to a strong-only
cipher list (Mozilla "Intermediate" baseline —
[ssl-config.mozilla.org](https://ssl-config.mozilla.org/), re-check
against that generator occasionally rather than treating this as
permanently hand-tuned): TLS 1.2 + 1.3 only (no 1.0/1.1), every TLS 1.2
suite is ECDHE/DHE (forward secrecy) + AEAD (GCM or ChaCha20-Poly1305) —
no RC4, 3DES, export ciphers, NULL ciphers, or static RSA/DH key exchange.
TLS 1.3's own 3 ciphersuites are all AEAD by spec, nothing to configure or
exclude there. Also sets `ssl_prefer_server_ciphers on`, disables session
tickets (no ticket-key-rotation infra here, and a static ticket key would
quietly undermine the forward secrecy the cipher list is for — the
non-ticket session cache still avoids a full handshake on reconnect), and
enables OCSP stapling (best-effort, silently skipped if the CA has no
responder or it's unreachable).

Not yet using the PQ-hybrid key exchange (X25519+ML-KEM) noted in the
architecture doc — that needs OpenSSL 3.5+, and the `nginx:1.27-alpine`
image here is built against 3.3.3 as of this writing (check with
`docker exec <nginx container> nginx -V`). Swap the base image once one
ships with a newer OpenSSL if that matters for your threat model.

Verify what actually negotiates against your own deployment:

```
openssl s_client -connect <your-domain>:443 -tls1_3 -brief </dev/null
```

#### CPU / worker count

Gunicorn defaults to a single worker process, which means the app never
uses more than one CPU core no matter how many the host has. `entrypoint.sh`
auto-sizes `--workers` to `(2 * nproc) + 1` (the standard gunicorn-recommended
formula) unless you set `GUNICORN_WORKERS` explicitly in `.env`. `nginx`
itself already uses `worker_processes auto;` — the base image's default — so
it was already using every core; this only affects the Django app process.

### Running the test suite

```
python manage.py test
```

## Contributing

- **Found a bug or want a feature?** Open an issue — the templates under
  `.github/ISSUE_TEMPLATE/` ask for the details that actually help
  reproduce a problem in a self-hosted Django app (version, install
  method, whether it reproduces on a clean instance).
- **Want to submit a change?** See [`CONTRIBUTING.md`](CONTRIBUTING.md)
  for dev-environment setup, test expectations, and PR conventions
  before opening one.
- **Found a security vulnerability?** Don't open a public issue for it —
  see [`.github/SECURITY.md`](.github/SECURITY.md) for private reporting.
- Everyone participating is expected to follow the
  [Code of Conduct](CODE_OF_CONDUCT.md).

## Versioning

[Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`, with a
`-alpha.N` / `-beta.N` / `-rc.N` pre-release suffix before the first
`1.0.0`. The current version lives in `VERSION` (repo root, single line,
no `v` prefix) and is tagged in git as `v<version>` (e.g. `v0.1.0-alpha.1`).
`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/) —
every release gets a dated entry there before being tagged.

Pre-1.0, expect breaking changes on minor bumps (`0.1.0` → `0.2.0`) — normal
during alpha, not a mistake. Once this reaches `1.0.0`, standard SemVer
compatibility rules apply: `PATCH` for fixes, `MINOR` for backward-compatible
additions, `MAJOR` for breaking changes.

See [`LICENSE`](LICENSE) and [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md)
for licensing terms.

To cut a new release: update `VERSION`, move `[Unreleased]` entries in
`CHANGELOG.md` into a new dated section, commit, then tag:

```
git tag -a v0.1.0-alpha.2 -m "v0.1.0-alpha.2"
git push origin v0.1.0-alpha.2   # if/when a remote is configured
```

## Alpha status

RedScribe is early alpha (`0.1.0-alpha.1`) — expect rough edges and
breaking changes between releases. Known limitations before relying on it
for a real engagement:

- **No public API** — every workflow is web-UI-driven.
- **Instance-wide MFA enforcement defaults off.** This is a deliberate
  admin-configurable default, not an oversight: the built-in Superadmin
  role always requires MFA regardless of this toggle, and any other role
  can be set to require it individually from Role Management. Flip the
  instance-wide toggle on too before a real deployment if you want MFA
  required for everyone.

See `CHANGELOG.md` for the full, dated history of what's changed release
to release.
