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

## [0.1.0-alpha.1] - 2026-09-17

Initial public release.
