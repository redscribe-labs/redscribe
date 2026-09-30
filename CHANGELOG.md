# Changelog

All notable changes to RedScribe. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, each
release carries an `-alpha.N` suffix and may include breaking changes.

## [Unreleased]

## [0.2.0-alpha.3] - 2026-09-30

A security and maintenance update. Upgrading is recommended for everyone.

### Security

- Updated the sign-in libraries to fix known vulnerabilities.
- Moved to a supported version of nginx.
- Added a missing security header to nginx's own error pages.

### Changed

- Routine updates to other dependencies.

## [0.2.0-alpha.2] - 2026-09-29

A bug-fix release for report fonts, User Management, and Docker setup.

### Fixed

- Report profile fonts now show up in the app and the report preview.
- Client portal users no longer appear in User Management.
- Fixed several problems that stopped RedScribe from starting, including on
  single-CPU hosts.

### Security

- The backup passphrase can now be stored as a secret file.

## [0.2.0-alpha.1] - 2026-09-22

A security hardening release. MFA is now on by default.

**Upgrading:** create `secrets/django_secret_key.txt` and
`secrets/postgres_password.txt` before starting this version. See
[`secrets/README.md`](secrets/README.md).

### Security

- Fixed two serious vulnerabilities in Word report templates and rich-text
  links.
- Passwords and keys are now kept in secret files instead of `.env`.
- Tightened the audit log, uploaded templates, and Docker builds.

### Added

- A command to recover a locked-out account.

### Changed

- MFA is on by default for every local account.
- Docker Compose now limits how much memory and CPU each service can use.

## [0.1.0-alpha.1] - 2026-09-17

Initial public release.
