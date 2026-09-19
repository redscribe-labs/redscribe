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

## [0.1.0-alpha.1] - 2026-09-17

Initial public release.
