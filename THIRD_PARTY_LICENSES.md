# Third-party licenses

RedScribe is dual-licensed (see [LICENSE](LICENSE) and
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)). This file lists the
third-party software and font files it bundles or depends on, and their
licenses, for anyone reviewing commercial-use compatibility.

Nothing listed below is GPL/AGPL-licensed or otherwise restricted against
commercial use. Two Python dependencies are LGPL — see the note under
Python dependencies.

## Fonts

All fonts bundled in this repository are licensed under the **SIL Open
Font License, Version 1.1** ("OFL"). The OFL requires its license text to
accompany redistributed copies of the font; the full text (with each
font's specific copyright/attribution line) ships alongside the files
themselves:

- `static/fonts/OFL.txt` — covers Plus Jakarta Sans, JetBrains Mono, and
  Source Code Pro, used for the web application's own UI.
- `apps/reports/seed_data/fonts/OFL.txt` — covers Open Sans, JetBrains
  Mono, and Plus Jakarta Sans, seeded into the `CachedGoogleFont` table
  for generated-report rendering (PDF/HTML).

A superadmin may also configure a Report Profile with any other Google
Fonts family via the live fetch-and-cache flow (`apps/reports/google_fonts.py`)
— those fonts carry whatever license Google Fonts publishes for them
(almost always OFL or Apache 2.0), fetched and cached at the point of
that explicit admin action, not bundled here.

## Vendored static assets (`static/vendor/`)

| File | License | Source |
|---|---|---|
| `flatpickr.min.css` | MIT | [flatpickr](https://github.com/flatpickr/flatpickr) (byte-identical to the npm package, `flatpickr@4.6.13`) |
| `cvss40.js` | BSD-style (FIRST.org/Red Hat) | [RedHatProductSecurity/cvss-v4-calculator](https://github.com/RedHatProductSecurity/cvss-v4-calculator) — retains its own full license header in-file |
| `highlight-github-light.css` | BSD-3-Clause | [highlight.js](https://github.com/highlightjs/highlight.js) "GitHub" theme, by @Hirse |
| `redscribe-editor.bundle.js` | MIT (aggregate) | esbuild bundle of Tiptap + extensions (see npm table below) |
| `redscribe-password-strength.bundle.js` | MIT (aggregate) | esbuild bundle of @zxcvbn-ts |
| `redscribe-datepicker.bundle.js` | MIT | esbuild bundle of flatpickr |

## Icons

Inline SVG icons in `templates/` are hand-authored in this repo. A small
number of simple geometric icons (e.g. the hamburger menu, chevron) match
common [Heroicons](https://github.com/tailwindlabs/heroicons) (MIT,
Tailwind Labs) path data — credited here for completeness.

## Python dependencies (`requirements.txt`)

Checked against each package's actual installed license metadata.

| Package | License |
|---|---|
| Django | BSD-3-Clause |
| django-allauth | MIT |
| PyJWT | MIT |
| requests | Apache-2.0 |
| django-otp | Unlicense |
| qrcode | BSD |
| Pillow | MIT-CMU |
| argon2-cffi | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| psycopg[binary] | **LGPL-3.0-only** |
| gunicorn | MIT |
| whitenoise | MIT |
| weasyprint | BSD |
| pypdf | BSD-3-Clause |
| docxtpl | **LGPL-2.1-only** |
| docxcompose | MIT |
| defusedxml | PSFL (Python Software Foundation License) |

**LGPL note:** `psycopg` and `docxtpl` are used unmodified, as ordinary
imported Python libraries — LGPL only imposes obligations (source
availability, relinking rights) if the library itself is modified and
redistributed, which does not happen here. No action is required for
commercial use.

## npm dependencies (build-time only)

All `package.json` entries are `devDependencies` — compiled at build time
into the committed bundles under `static/vendor/`; nothing here ships as
source or is installed at runtime. Checked via `license-checker` against
the full installed tree (108 packages including transitive dependencies):

| License | Count |
|---|---|
| MIT | 98 |
| MPL-2.0 | 3 (`lightningcss` and its platform binaries — weak copyleft; only affects modifications to lightningcss itself, not this project's code) |
| Apache-2.0 | 2 |
| ISC | 2 |
| BSD-3-Clause | 1 |
| BSD-2-Clause | 1 |
| Python-2.0 | 1 (`argparse`, permissive despite the name) |

(The one `UNLICENSED` entry found is this project's own local, unpublished
build-tooling `package.json` — not a third-party dependency.)
