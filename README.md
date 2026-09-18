# RedScribe

**`0.1.0-alpha.1`** — self-hosted engagement, finding, checklist, and report
management for a small penetration testing team.

![version](https://img.shields.io/badge/version-0.1.0--alpha.1-blue)
![license](https://img.shields.io/badge/license-source--available-orange)

[Documentation](https://docs.redscribe.app) ·
[Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) ·
[Security Policy](.github/SECURITY.md) · [Changelog](CHANGELOG.md)

Django + HTMX + Tailwind, Postgres, per-engagement AES-256-GCM encryption
for sensitive fields. **This is alpha software** — not yet
production-ready; see [Alpha status](#alpha-status) below before relying
on it for a real engagement.

This README covers licensing, a quickstart, and where to go next.
**Everything else — every install method, the full configuration
reference, the user guide, the security model, and the developer guide —
lives at [docs.redscribe.app](https://docs.redscribe.app).**

## Table of contents

- [License](#license)
- [What's inside](#whats-inside)
- [Quickstart](#quickstart)
- [Contributing](#contributing)
- [Versioning](#versioning)
- [Alpha status](#alpha-status)

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

## What's inside

A short highlight list, not the full picture — see the
[User Guide](https://docs.redscribe.app) and
[Security](https://docs.redscribe.app) sections of the docs for the
complete feature set.

- Engagement → finding → report workflow: draft → review → QA, CVSS
  v3.1/v4.0, retest tracking, and recurring-vulnerability detection.
- A shared report IR driving Markdown/PDF/HTML/DOCX export from one
  source — DOCX fills in your own uploaded Word template rather than
  generating from scratch.
- Per-engagement AES-256-GCM encryption at rest, dynamic RBAC, TOTP MFA,
  and an append-only, hash-chained audit log with tamper detection.
- A read-only client portal, checklist runs (OWASP WSTG and your own
  templates) with Nmap/Burp Suite/Nuclei scanner import, and
  cross-engagement trend reporting.
- Server-side encrypted backup/restore, and Docker Compose deployment
  with automated Tailscale TLS or a bring-your-own certificate.

## Quickstart

The fastest way to try it locally — no TLS, no domain:

```
cp .env.example .env
# set DJANGO_SECRET_KEY and POSTGRES_PASSWORD in .env
docker compose up -d --build
docker compose exec web python manage.py generate_root_key
# copy the printed value into secrets/root_key.txt, then:
docker compose up -d web
```

Open `http://localhost:8000/setup/` to create the first Superadmin — TOTP
MFA enrollment happens automatically on first login.

For a real deployment (automated Tailscale HTTPS, your own TLS
certificate, sizing guidance, and the full environment variable
reference), see **[Installation](https://docs.redscribe.app/getting-started/installation)**
and **[Configuration](https://docs.redscribe.app/getting-started/configuration)**
in the docs.

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
`1.0.0`. The current version lives in `VERSION` (repo root) and is tagged
in git as `v<version>`. `CHANGELOG.md` follows
[Keep a Changelog](https://keepachangelog.com/) — every release gets a
dated entry there before being tagged. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the release-cutting steps.

Pre-1.0, expect breaking changes on minor bumps (`0.1.0` → `0.2.0`) —
normal during alpha, not a mistake.

## Alpha status

RedScribe is early alpha (`0.1.0-alpha.1`) — expect rough edges and
breaking changes between releases. Two things worth knowing before
relying on it for a real engagement (full list in the docs):

- **No public API** — every workflow is web-UI-driven.
- **Instance-wide MFA enforcement defaults off.** Deliberate, not an
  oversight: the built-in Superadmin role always requires MFA regardless;
  any other role can be set to require it individually from Role
  Management. Flip the instance-wide toggle on too before a real
  deployment if you want MFA required for everyone.

See `CHANGELOG.md` for the full, dated history of what's changed release
to release.
