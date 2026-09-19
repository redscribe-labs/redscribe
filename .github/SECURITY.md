# Security Policy

## Scope

This policy covers **vulnerabilities in RedScribe itself** — the
application code, its default configuration, and the deployment methods
documented in the README.

It does **not** cover the pentest/security-assessment data that RedScribe's
users store about their own clients — securing that data on your own
deployment (network placement, access control, backups, TLS, MFA
enforcement) is the operator's responsibility. See the README's
Installation and Configuration sections for the hardening this project
already builds in — per-engagement AES-256-GCM encryption at rest, a
hash-chained tamper-evident audit log, TOTP MFA, and secure session/cookie
defaults, among others.

Also out of scope: gaps already tracked publicly as known limitations —
see the [Alpha status & versioning](https://docs.redscribe.app/start/alpha-status/#known-limitations)
page's "Known limitations" section. Those are accepted, disclosed
alpha-status gaps, not undiscovered vulnerabilities, so please don't file
a fresh advisory for something already listed there — a comment on the
relevant issue/discussion is more useful.

## Supported Versions

RedScribe is currently in alpha (`0.x`). Only the latest tagged `0.x`
release receives security fixes — there's no long-term-support branch at
this stage.

| Version         | Supported |
| --------------- | --------- |
| Latest `0.x`    | ✅        |
| Older `0.x` tags | ❌       |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for a security vulnerability.**

Use GitHub's private vulnerability reporting instead: go to the
**Security** tab on this repository → **Report a vulnerability**. If that
isn't available (e.g. the repo is still private), email
`redscribe.maintainer@proton.me` with details instead.

Please include:

- The version/commit you're testing against.
- Steps to reproduce, or a proof of concept.
- The impact you believe it has (what an attacker could actually do).

We'll acknowledge reports on a best-effort basis — this is a small,
source-available project without a dedicated security team or a
guaranteed response-time SLA, but we do take reports seriously and will
credit reporters (if desired) once a fix ships.
