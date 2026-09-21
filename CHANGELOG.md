# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) —
`MAJOR.MINOR.PATCH`, with `-alpha.N` / `-beta.N` / `-rc.N` pre-release
suffixes before the first `1.0.0`. See the "Versioning" section of
`README.md` for how this is applied in practice.

## [Unreleased]

## [0.2.0-alpha.1] - 2026-09-22

### Security

- `mfa_required` now defaults to **on** instead of off. Every local account
  is enrolled in TOTP MFA from first login unless an admin explicitly
  disables the instance-wide flag (Feature Flags), same as before for a
  local/disposable dev or test instance. Existing instances are migrated to
  the new default on upgrade; flip it back off from Feature Flags if you
  need the old behavior.
- Added `emergency_account_recovery` management command. Resetting a
  locked-out local account's password (and optionally clearing its TOTP
  device) previously meant a raw `manage.py shell`/`changepassword` session
  that left no trace in RedScribe's own audit log — the one access path
  that matters most during an incident was invisible to it. The new
  command wraps the same recovery actions behind a required `--reason` and
  writes an audit log entry for the action.
- The permanent-engagement-delete confirmation page now discloses that a
  database backup taken before the deletion still contains the deleted
  engagement's data until that backup separately ages out or is cleaned up
  — deletion only ever touched the live database, but the page previously
  implied otherwise. Documented further under Backup & restore.
- `AUDIT_LOG_RETENTION_DAYS` and `SESSION_IDLE_TIMEOUT_SECONDS` in
  `config/settings/base.py` now carry their compliance rationale (HIPAA
  documentation-retention and automatic-logoff figures, plus a PCI
  DSS/CIS/NIST retention comparison) as an in-code comment instead of only
  in the docs, which had drifted to cite a comment that didn't exist.
- **Fixed a server-side template injection vulnerability in Word (.docx)
  report export.** Uploaded `.docx` templates were rendered through an
  unrestricted `jinja2.Environment` (via `docxtpl`), so a crafted template
  could reach Python internals (e.g. `''.__class__.__mro__`) and
  potentially execute arbitrary code on the server. Both render paths
  (upload-time validation and real export) now go through
  `jinja2.sandbox.SandboxedEnvironment` instead.
- The audit log's "Clear all logs" action now requires a second, currently
  active Superadmin's username and password, entered at confirmation time
  — not just the person already holding `audit_log.manage`. A full purge is
  the one action that could undo the hash-chain's own tamper-evidence
  guarantee (an insider covering their tracks), so it's no longer left to
  a single permission holder acting alone.
- The uploaded `.docx` report template now has an explicit 20MB size cap,
  plus a check on the archive's own declared uncompressed size and member
  count before it's ever opened by `python-docx`/`docxtpl` — closes a
  zip-bomb-style resource-exhaustion path that the size cap alone didn't
  cover.
- A `.docx` template's original filename is now sanitized before being
  used in a download's `Content-Disposition` header, closing a
  header-injection primitive for a filename containing an unescaped `"`.
- Added `.dockerignore` (`.env`, `secrets/*.txt`, `certs/*.pem`, `.git/`,
  etc.). `Dockerfile`'s `COPY . .` had no exclusions, so any of these
  present in the build context at `docker build` time would get baked
  into the image layer despite being `.gitignore`d — gitignore has no
  effect on Docker's build context.
- Postgres connections now set `sslmode` explicitly (default `prefer`,
  matching the shipped same-host Compose topology, but configurable via
  `POSTGRES_SSLMODE`/`POSTGRES_SSLROOTCERT`) instead of relying on
  psycopg's undocumented default — matters once `POSTGRES_HOST` points at
  a separate host.
- **Fixed a stored-XSS path in rich text link marks.** Finding and
  checklist rich text fields already stripped image `src` values down to
  an allowlist (own encrypted blobs, or nothing); the equivalent check was
  missing for link `href` values, so a `content_json` payload POSTed
  directly (bypassing the Tiptap editor's own client-side protocol
  allowlist) could carry a `javascript:` link that survived to a
  higher-privileged reviewer or the client portal. `RichTextField` now
  strips any link whose `href` isn't `http://`, `https://`, or `mailto:`,
  the same allowlist the read-only renderer already enforces.
- `reports:preview` (the live report-preview endpoint, which serves
  fully-assembled decrypted report content) is no longer excluded from the
  audit log. It was originally excluded to avoid flooding the log on every
  keystroke of report configuration; that traded away a record of the one
  endpoint that serves decrypted report content on demand, so it's logged
  like every other view now.
- `rotate_root_key` no longer requires `--new-key` on the command line.
  Omitting it now prompts interactively via `getpass` (not echoed, never
  in argv or shell history), matching `restore_backup`'s existing pattern
  for the same class of secret.
- `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` are now delivered the same
  way `REDSCRIBE_ROOT_KEY` already was under Docker Compose: as file-based
  Docker secrets (`secrets/django_secret_key.txt`,
  `secrets/postgres_password.txt`) rather than plain `.env` values, via a
  new `env_secret()` settings helper (`<NAME>_FILE` beats `<NAME>`, same
  convention `RootKeyProvider` already used). The same mechanism is now
  also available for `GOOGLE_OAUTH_CLIENT_SECRET`,
  `MICROSOFT_OAUTH_CLIENT_SECRET`, and `EMAIL_HOST_PASSWORD`, though
  Compose doesn't mount a secret for those by default since they're
  opt-in features. **Existing `.env`-only deployments upgrading to this
  release need to create `secrets/django_secret_key.txt` and
  `secrets/postgres_password.txt`** — see `secrets/README.md`. The plain
  env vars remain a supported fallback for non-Docker/bare-metal
  deployments and CI.
- `docker-compose.yml` now caps memory/CPU per service (`WEB_MEM_LIMIT`/
  `WEB_CPUS`, `DB_MEM_LIMIT`/`DB_CPUS`, `NGINX_MEM_LIMIT`/`NGINX_CPUS`),
  defaulting to the "Small firm" tier from the docs' Requirements &
  sizing table. Previously unbounded, which on a host without its own
  container-level limits meant a single large report export (or a burst
  of them) had no ceiling on how much of the box it could consume.
  Existing deployments sized for a bigger tier should raise these
  explicitly in `.env`.
- Corrected "tamper detection"/"tamper-evident" language describing the
  audit log in the README, `SECURITY.md`, and the docs site. The hash
  chain reliably detects an edit to a row that's still in the table, but
  does **not** protect against someone with direct database write access
  deleting the newest entries, or an already-purged prefix being extended
  further than a legitimate retention purge would — both leave the chain
  verifying as intact. See [Audit trail &
  integrity](https://docs.redscribe.app/security/audit-trail/) for the
  full scope of what the hash chain does and doesn't catch.

## [0.1.0-alpha.1] - 2026-09-17

Initial public release.
