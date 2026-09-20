# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) —
`MAJOR.MINOR.PATCH`, with `-alpha.N` / `-beta.N` / `-rc.N` pre-release
suffixes before the first `1.0.0`. See the "Versioning" section of
`README.md` for how this is applied in practice.

## [Unreleased]

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

## [0.1.0-alpha.1] - 2026-09-17

Initial public release.
