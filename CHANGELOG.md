# Changelog

All notable changes to RedScribe. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, each
release carries an `-alpha` suffix and may include breaking changes.

## [Unreleased]

## [0.8.0-alpha] - 2026-11-13

### Added

- Per-engagement structured scope: typed assets (URL, IP, subnet, FQDN) under
  named asset groups (e.g. Internal, External), each with a notes field.
  Managed from the new "Manage scope" page.
- Checklist templates can be archived. An archived template is retired from the
  new-run picker, so new engagements can't start a run from it, while runs
  already started keep working (each run snapshots its template's items when it
  starts). Archive or restore from the template library, which now has **Active**
  and **Archived** tabs; an archived template can't be the default.
- Network-penetration-test reports: a report profile can split findings by
  asset group into one section per group, each with its own findings table,
  while the overall severity chart stays combined over all findings. Turned on
  per profile with "Split findings by asset group". New profile/DOCX tags:
  `grouped_findings` and `scope_table`.
- Findings carry an asset group. The field is shown and required only on
  engagements whose report profile splits by asset group, and grouped-report
  export is blocked until every included finding is tagged. The findings list
  shows each finding's asset group as a badge.

### Changed

- The breakdown-of-findings chart now stacks open and closed counts in one bar
  per severity — open in full colour, closed in a lighter shade — with a key,
  instead of two separate bars.
- Scope change requests are now review notes: approval records the decision and
  notifies, and a manager applies the change on the Manage scope page.
- Dependencies: Django 5.2.19, django-allauth 65.22.0, psycopg 3.3.9. The
  container image now runs on Python 3.14, and the browser password-strength
  meter was rebuilt on zxcvbn-ts 4.
- The bundled PostgreSQL client (`pg_dump`/`pg_restore`, used by backups) is now
  version 18, installed from the PGDG apt repo since Debian ships only 17. It
  backs up both 17 and 18 servers.
- **Breaking (operators): the `db` service moves to PostgreSQL 18.** The 18
  image stores its data in a major-version subdirectory and mounts the volume at
  `/var/lib/postgresql` (not `.../data`), and it will **refuse to start on an
  existing 17 data directory** — the upgrade is a backup-and-restore, not an
  in-place pull. On a fresh install there is nothing to do. To upgrade an
  existing 17 deployment, while it is still running on 17:
  1. Back up: `docker compose exec web python manage.py create_backup` — note
     the resulting `./backups/*.rsbk` file and your `BACKUP_ENCRYPTION_PASSPHRASE`.
  2. `docker compose down`, then pull/build this release.
  3. Remove the old 17 volume so 18 initialises fresh:
     `docker volume rm redscribe_pgdata` (confirm the name with `docker volume ls`).
  4. `docker compose up -d --build` — the 18 server starts empty and `web`
     applies migrations.
  5. Restore: `docker compose exec web python manage.py restore_backup
     /app/backups/<file>.rsbk` (it writes a pre-restore safety snapshot first).

### Removed

- **Breaking:** the free-text engagement scope field. Existing scope text is
  migrated into a single "In Scope" asset group. The `{{ scope }}` report
  placeholder now renders the structured scope; DOCX templates that used the
  old free-text `scope` should switch to `{{p scope_table }}`.

### Fixed

- Breadcrumbs now appear on the checklist-template pages (the template library,
  a template, and the item editors), which previously had none.

## [0.7.0-alpha] - 2026-11-06

### Security

- Login throttling now also blocks by IP address, with an escalating lockout.

### Added

- Archive findings, with Active and Archived tabs. Archived findings stay out
  of reports and the client portal.
- Add a comment by selecting text in a finding; hover or tap to read comments.
- Retests now close, reopen, or leave a finding based on the outcome.
- New grantable permissions: access archived engagements, permanently delete an
  engagement, and erase a client user.
- Active and Deactivated tabs in User Management, and erasing a deactivated
  person's details (their work stays as "Erased user").

### Changed

- "Vulnerability" is now "finding" throughout.
- Reviewer and QA independence is enforced unless a role allows reviewing or
  QA'ing its own work.
- Engagements can't reach Approved or Delivered until all active findings are
  QA-approved.
- CVSS score, vector, and severity are checked for consistency.
- Archiving now confirms in a pop-up instead of a separate page.
- Page alignment and widths made consistent, and help text shortened.
- Removing an engagement member clears their assignments there.
- Deactivating a client also deactivates its portal users.
- The Retest workflow setting is gone; engagement status decides retesting.
- Clearing the audit log no longer needs a second Superadmin.
- Classifications are optional on findings and templates.
- Signing out only works from the sign-out button.

### Fixed

- Severity labels are now readable on closed findings in dark mode.
- Clicks that occasionally missed, and an error when deleting a report text block.
- Classifications typed but not added were lost on save.
- Portal users of an inactive client couldn't be edited.
- Forms could clear a deactivated person or inactive client.
- Deactivated people could still be assigned findings to review.
- The export page now warns when a report has no layout.
- Various phone, keyboard, and screen-reader fixes.

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
