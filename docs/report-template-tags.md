# Report Template Tags

RedScribe reports are authored as one free-form document per Report Profile (the
**Document** tab on a profile's edit page). You write headings for structure and drop
`{{ tag }}` placeholders wherever you want dynamic content to appear. This file documents
every tag currently available, how each behaves, and the rules for how they combine.

There are three independent tag systems. They look the same (`{{ name }}`) but behave
differently — see [How the systems differ](#how-the-systems-differ) before relying on
edge-case behavior.

## 1. Placeholder tags (data substitution)

Simple text substitution — the tag is replaced with a plain string value from the current
engagement/user. These work **anywhere** text can appear: directly in the Document body,
and (as of 2026-09-08) inside any custom text block's content, any finding section, retest
notes, observations, and testing-phase entries.

| Tag | Value |
|---|---|
| `{{ client_name }}` | `Engagement.client_name` |
| `{{ reference_number }}` | `Engagement.reference_number` |
| `{{ scope }}` | `Engagement.scope` (free text) |
| `{{ start_date }}` | `Engagement.start_date`, ISO format, or empty if unset |
| `{{ end_date }}` | `Engagement.end_date`, ISO format, or empty if unset |
| `{{ report_date }}` | Today's date (ISO format), computed at render time |
| `{{ prepared_by }}` | The user generating the report, or empty if none |

If a placeholder tag's name isn't recognized, it's left in the output unchanged (e.g. a
typo like `{{ cilent_name }}` prints literally rather than erroring or vanishing).

## 2. Structural tags (built-in report blocks)

Each of these pulls in a specific chunk of real engagement/finding data. They only work as
a **standalone paragraph** in the Document template — put the tag alone on its own line,
directly under the heading you want it to belong to. They **cannot** be used inside a text
block, finding section, or anywhere else — only in the Document body itself.

| Tag | What it renders | Notes |
|---|---|---|
| `{{ breakdown_of_findings }}` | Severity/status bar chart (with a table fallback) plus a vulnerabilities summary table (ID, severity, title, status) | |
| `{{ finding_details }}` | The full write-up for every included finding — metadata table, affected assets, each active finding section (see [Finding sections](#finding-sections-inside-finding_details) below), and (on a remediation report) retest history | This is the main body of the report — almost always required |
| `{{ observations }}` | Free-form dynamic entries configured per-engagement (title + rich content), each as its own subsection | Empty/omitted entirely if none are configured — no placeholder text shown |
| `{{ testing_phases }}` | Same pattern as observations — free-form per-engagement phase entries | Empty/omitted if none are configured |
| `{{ assessment_team }}` | One subsection per engagement member with access, showing their bio and qualifications | Omitted entirely if the engagement has no members |
| `{{ checklist_coverage }}` | The engagement's checklist run(s), grouped by category, showing item status and any linked findings | Shows a graceful "No checklist runs have been recorded for this engagement." message if none exist — never errors |
| `{{ scan_imports }}` | A table documenting each scanner import on this engagement (tool, filename, date, imported by, findings produced) | Metadata only — the original uploaded scan file itself is never stored, only this record of the import. Shows a graceful "No scanner imports have been recorded for this engagement." message if none exist |

### Finding sections inside `{{ finding_details }}`

`{{ finding_details }}` doesn't have its own separate tag list — it automatically includes
every **active** `ContentSectionDefinition` (Finding Structure), in their configured order.
As of this writing, the active sections are:

| Order | Slug | Label | Supports images | Visible on client portal |
|---|---|---|---|---|
| 10 | `vulnerability-description` | Vulnerability description | No | Yes |
| 20 | `business-impact` | Business impact | No | Yes |
| 30 | `testing-summary` | Testing summary | No | Yes |
| 40 | `technical-details` | Technical details | Yes | Yes |
| 50 | `remediation-testing` | Remediation testing | Yes | No |
| 60 | `recommendations` | Recommendations | No | Yes |
| 70 | `references` | References | No | Yes |

These are managed from the Finding Structure admin screen, not the Document editor — adding,
reordering, or deactivating one changes what `{{ finding_details }}` includes for every
profile, immediately.

## 3. Custom text-block tags (author-defined prose)

These are admin-authored rich-text blocks (`ReportTextBlockDefinition`) — the way you add
your own prose sections (executive summary, disclaimers, methodology, etc.) without touching
code. Like structural tags, they only work as a **standalone paragraph** in the Document
template.

A text block always belongs to exactly one Report Profile — there's no shared/global text
block that every profile automatically resolves. Its metadata (slug, label) lives on the
`ReportTextBlockDefinition` row; its actual rich-text content lives in that profile's own
`block_defaults[slug]` (or a per-report override, set from the report's Configure page). If a
tag doesn't match a structural tag or a text block on the *current* profile, it falls back to
placeholder substitution (see [How the systems differ](#how-the-systems-differ)); if that also
finds nothing, the tag is left as literal text.

New text blocks are created from a profile's own **Text blocks** tab — whatever slug you give
one becomes its tag name automatically. The "Default Penetration Test Report" profile (see
`python manage.py seed_pentest_report_format`) ships with a worked example set:

| Tag | Label |
|---|---|
| `{{ executive_summary }}` | Executive Summary |
| `{{ risk_narrative }}` | Overall Risk Posture |
| `{{ root_cause_analysis }}` | Root Cause Analysis |
| `{{ effective_security_practices }}` | Effective Security Practices |
| `{{ additional_recommendations }}` | Additional Recommendations |
| `{{ rules_of_engagement }}` | Rules of Engagement |
| `{{ out_of_scope }}` | Out-of-Scope Items |
| `{{ emergency_contacts }}` | Emergency Contacts |
| `{{ testing_methodology }}` | Testing Methodology |
| `{{ cvss_scoring_methodology }}` | CVSS Scoring Methodology |
| `{{ risk_rating_matrix }}` | Risk Rating Matrix |
| `{{ tools_used }}` | Tools Used |
| `{{ tester_credentials }}` | Tester Credentials |
| `{{ glossary }}` | Glossary of Terms |
| `{{ conclusion }}` | Conclusion |
| `{{ confidentiality_disclaimer }}` | Confidentiality & Disclaimer |

These slugs aren't reserved or built-in — they're just what that one profile happens to use.
A different profile is free to use different slugs entirely.

> **Profile-specific blocks behave differently from global ones.** A global block
> (`profile=None`) uses its own `content` field directly. A profile-specific block instead
> reads from that profile's `block_defaults[slug]` (or a per-report override), and ignores
> its own `content` field entirely. If you create a profile-scoped text block and its content
> doesn't seem to render, this is why — set the value via the profile's block-defaults UI, not
> the block's own content editor.

## How the systems differ

| | Placeholder tags | Structural tags | Custom text-block tags |
|---|---|---|---|
| Where usable | Anywhere (Document body, text blocks, finding sections, observations, etc.) | Only as a standalone paragraph in the Document template | Only as a standalone paragraph in the Document template |
| Resolves to | A plain string | A pre-built report section (table/chart/list) | Rich text (headings, lists, links, etc.) |
| Unknown tag | Printed literally, unchanged | Falls through to a custom-tag lookup, then a placeholder lookup, then printed literally | Falls through to a placeholder lookup, then printed literally |
| Recursive/nested? | No — single substitution pass, not re-scanned | No — resolved once per Document parse, never re-invoked on nested content | No — same as structural tags |

**No tag system is recursive.** A structural or custom tag is only recognized while
RedScribe is walking the Document template itself; once resolved, its output is never fed
back through tag resolution again. So a text block cannot reference another text block or a
structural tag and have it expand — only a placeholder tag (`{{ client_name }}` etc.) works
inside nested content, and even that is a single non-recursive substitution pass. This is a
deliberate design choice, not a current limitation — it guarantees output is always bounded
and predictable, with no risk of infinite loops or runaway expansion from user-authored
content.

## Practical example

A minimal but complete Document template:

```
# Executive Summary
{{ executive_summary }}

# Scope, Rules of Engagement & Contacts
## Rules of Engagement
{{ rules_of_engagement }}
## Out-of-Scope Items
{{ out_of_scope }}
## Emergency Contacts
{{ emergency_contacts }}

# Testing Methodology
{{ testing_methodology }}
## Testing Coverage (Checklist)
{{ checklist_coverage }}

# Assessment Team
{{ assessment_team }}

# Breakdown of Findings
{{ breakdown_of_findings }}

# Detailed Findings
{{ finding_details }}

# Appendix: Scanner Imports
{{ scan_imports }}

# Confidentiality & Disclaimer
{{ confidentiality_disclaimer }}
```

For a fuller worked example (executive summary, root cause analysis, effective security
practices, additional recommendations, a conclusion, and every appendix), see the profile
built by `python manage.py seed_pentest_report_format`.

Within `{{ executive_summary }}`'s own authored content, you could write:

```
This assessment was performed for {{ client_name }} between {{ start_date }} and
{{ end_date }}, under reference {{ reference_number }}.
```

— and `client_name`/`start_date`/`end_date`/`reference_number` will substitute correctly, per
engagement, every time the report is rendered.
