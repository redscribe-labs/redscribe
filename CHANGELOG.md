# Changelog

All notable changes to RedScribe. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, each
release carries an `-alpha` suffix and may include breaking changes.

## [0.6.0-alpha] - 2026-10-22

A redesign of the whole app, with a new checklist workflow. The database
updates itself when you upgrade; as always, take a backup first.

Version numbers no longer carry a number after "alpha". Earlier releases
have been renumbered to match: 0.2.0-alpha.1 to .4 are now 0.2.0-alpha to
0.5.0-alpha.

### Security

- Image uploads only accept genuine PNG, JPEG, GIF, or WebP files.
- Updated Django, Pillow, and other libraries to fix known vulnerabilities.
- Checklist template imports remove unsafe links, and rich text nested too
  deeply to check is now rejected instead of passing through.

### Added

- A testing posture page for each checklist: coverage by category, where
  the risk is, blocked checks, and what's still untested.
- A redesigned checklist item page with an assignee, a **Blocked** outcome,
  a note of what was tested, a history, and automatic saving.
- Raise a finding straight from a checklist item, and start a checklist
  when you create an engagement.
- Imports from scanners and the catalogue show what they'll create before
  saving, leave likely duplicates unticked, and warn about content that
  would be lost.
- Home lists everything waiting on you. The engagement and finding lists
  gain tabs, filters, and a preview pane.
- Audit log export as CSV, and keyboard shortcuts across the app.

### Changed

- A new layout: a reorganized sidebar, breadcrumbs, and one **Settings**
  area for every admin page.
- The CVSS calculator opens in a pop-up, with a button for each metric and
  a live score.
- Reports say **Vulnerability ID**, list the assessment team by name only,
  and leave out the CVE row when a finding has none.
- Only one finding section can receive scanner import details.
- A checklist item's reference is read-only while testing. Edit it on the
  checklist template; each engagement keeps the copy it started with.
- Checklist template export now includes the template's name and
  description, with each reference easy to read. Import still accepts older
  files, and uses the name and description in the file when you leave those
  boxes blank.

### Fixed

- Client users now stay in the portal after signing in with MFA or
  changing their password.
- Editor toolbars no longer cover the page tabs or the text being edited,
  and several pages fit better on phones.
- The label on a report's cover no longer overlaps the title when there's
  no logo.
- Many accessibility fixes, including contrast, form labels, and names for
  screen readers.
- A bad row in an imported checklist template now stops the import with a
  message naming the row, instead of a server error.
- Importing a checklist template can no longer replace an existing one
  unless you type its name.

## [0.5.0-alpha] - 2026-10-06

A small maintenance release. When you upgrade, follow the updated upgrade
steps so your containers also pick up the latest OS security fixes.

### Fixed

- The sidebar collapse button now appears on large screens.
- The editor's floating menu and toolbar no longer cover the Cancel and Back
  buttons.

### Security

- The upgrade steps now refresh the PostgreSQL, nginx, and Python base
  images, so OS and library security fixes, such as OpenSSL updates, reach
  existing installs.
- Updated a build-time dependency to fix a known vulnerability.

## [0.4.0-alpha] - 2026-09-30

A security and maintenance update. Upgrading is recommended for everyone.

### Security

- Updated the sign-in libraries to fix known vulnerabilities.
- Moved to a supported version of nginx.
- Added a missing security header to nginx's own error pages.

### Changed

- Routine updates to other dependencies.

## [0.3.0-alpha] - 2026-09-29

A bug-fix release for report fonts, User Management, and Docker setup.

### Fixed

- Report profile fonts now show up in the app and the report preview.
- Client portal users no longer appear in User Management.
- Fixed several problems that stopped RedScribe from starting, including on
  single-CPU hosts.

### Security

- The backup passphrase can now be stored as a secret file.

## [0.2.0-alpha] - 2026-09-22

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

## [0.1.0-alpha] - 2026-09-17

Initial public release.
