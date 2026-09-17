# Word (.docx) Template Guide

This is for whoever designs the `.docx` file uploaded to a Report Profile's **Word (.docx)**
tab. Unlike the Document tab's own free-form template (see
[`report-template-tags.md`](report-template-tags.md)), a DOCX template is a real Word
document you build yourself, with your own layout, page setup, headers/footers, and named
styles — RedScribe fills it in, it doesn't generate one from scratch.

## How it works, in short

1. Design your report layout in Word, however you like.
2. Define named paragraph/character/table **styles** for anything content needs to look a
   particular way — a code block, an image caption, a quote, a table. Give them whatever
   names you want.
3. Drop placeholder **tags** where dynamic content should appear (see the reference below).
4. Upload the `.docx` on the profile's Word (.docx) tab.
5. On the style-mapping page that follows, tell RedScribe which of *your* styles is "the
   code block style", "the image caption style", etc.
6. Generate a test export against a real engagement, open it in Word, and iterate.

A profile with no `.docx` uploaded simply has no Word export option — nothing breaks, it's
just not offered.

## Two kinds of tag

| | Syntax | Use for | What it does |
|---|---|---|---|
| Plain | `{{ tag }}` | Single values — names, dates, numbers, labels | Replaces just the tag's text, keeping whatever formatting (bold, font, color) the tag's own run already has in your document |
| Rich | `{{p tag }}` | Multi-paragraph content — descriptions, technical details, tables, anything with images or code | Splices in real Word content built from the underlying data, styled using your mapped styles (see below) |

**The `{{p ...}}` form is mandatory for anything rich** — a plain `{{ tag }}` can only ever
hold a single run of text; it cannot contain a new paragraph, an image, or a table. Using
plain `{{ }}` on a rich tag by mistake won't error, but the tag will render literally
instead of the content you expect.

Put a `{{p tag }}` tag alone on its own paragraph/line. It gets replaced by that whole
paragraph's worth of content — you don't need to add extra blank paragraphs around it.

## The finding loop

Everything belonging to a finding — its title, severity, and rich-text sections — lives
inside a repeating block. Wrap it in:

```
{%p for finding in findings %}
... your per-finding layout, using finding.* tags below ...
{%p endfor %}
```

`{%p for %}` repeats a run of **paragraphs** once per finding — use this for the normal
case (a finding with a heading, metadata line, and several rich sections). If your layout
instead repeats a single **table row** per finding, use the table-row form instead:

```
{%tr for finding in findings %}
| {{ finding.id }} | {{ finding.title }} | {{ finding.severity }} |
{%tr endfor %}
```

(as an actual Word table row, not literal pipe characters — put the loop tags in the first
and last cells of the row you want repeated.)

Both loop forms need their matching `endfor` — a missing one is the single most common
template mistake, and is caught automatically when you upload (see
[Validation](#validation-what-gets-caught-and-when) below).

## Tag reference

Everything below is also shown live on the profile's Word (.docx) tab, since the
finding-loop rich-tag list depends on which content sections your deployment currently has
active (see [Content sections](#content-sections-are-dynamic) below).

### Anywhere in the document — plain values

| Tag | Value |
|---|---|
| `{{ client_name }}` | Engagement's client name |
| `{{ reference_number }}` | Engagement's reference/project number |
| `{{ scope }}` | Engagement's recorded scope (free text) |
| `{{ start_date }}` | Engagement start date (ISO format), blank if unset |
| `{{ end_date }}` | Engagement end date (ISO format), blank if unset |
| `{{ report_date }}` | Today's date, computed at render time |
| `{{ prepared_by }}` | The user generating the report |
| `{{ cover_title }}` | The profile's configured cover title |
| `{{ classification_label }}` | The profile's configured classification label (e.g. "Strictly Confidential") |
| `{{ firm_name }}` | Firm name, from Report Settings |
| `{{ test_type_label }}` | The engagement's test type (e.g. "Web Application Penetration Test"), blank if unset |
| `{{ reviewed_by }}` | The engagement's configured default reviewer, blank if none set |
| `{{ qa_by }}` | The engagement's configured default QA approver, blank if none set |
| `{{ approved_by }}` | The engagement's configured default approver, blank if none set |

`reviewed_by`/`qa_by`/`approved_by` reflect the engagement's *configured* role assignment,
not necessarily whoever actually clicked the button for a given finding — review and QA
happen per finding and can, in principle, involve someone other than the configured
default (e.g. a Superadmin acting on someone else's behalf). For a full, factual record of
who did what and when, use `{{p document_control }}` instead, which is built from the
engagement's real status-change history.

### Anywhere in the document — rich content

| Tag | Renders |
|---|---|
| `{{p firm_logo }}` | The firm logo (Report Settings), as an embedded picture — omit if you don't want it, or place it yourself in a header instead |
| `{{p document_control }}` | A table of the engagement's status history (stage / date / changed by) |
| `{{p assessment_team }}` | One heading + bio + qualifications list per engagement member with access |
| `{{p checklist_coverage }}` | The engagement's checklist run(s), grouped by run then category, as headings + tables |
| `{{p scan_imports }}` | A table documenting each scanner import on this engagement (tool, filename, date, imported by, findings produced) — metadata only, the original uploaded file itself isn't stored |
| `{{p breakdown_table }}` | A severity/status bar chart, followed by the same counts as a table with each cell shaded using the profile's configured severity colors |

### This profile's own text blocks

Every custom text block you've defined on this profile's **Text blocks** tab (e.g.
`information_gathering`, `disclaimers`, `executive_summary` — whatever slugs you've
created) is available as a `{{p <slug> }}` rich-content tag, using **this profile's own
default content** for that block (or a per-engagement override, if the report's Configure
page has one set). The current list of valid slugs for this profile is always shown live
on this tab.

**Use `{{p slug }}`, not `{{ slug }}`** — same rule as everywhere else: these are rich text
(can contain paragraphs, code blocks, images), so the plain-tag form can't hold them. A
plain `{{ information_gathering }}` won't error — Jinja just silently renders it as nothing,
which looks exactly like "the block is empty" even when it has real content. If your
export has an unexpectedly blank section where a text block should be, this is the first
thing to check.

`{{p breakdown_table }}` renders a bar chart image (drawn to match the PDF/HTML/preview
bars — same colors, same bars) followed by the counts table, since Word has no native
charting object python-docx can build directly; the chart is a raster image, not an
editable Word chart.

### Loops you write yourself: observations and testing phases

`observations` and `testing_phases` (free-form per-engagement entries configured on the
report's Configure page) aren't single tags — they're **lists** you loop over yourself,
the same pattern as the finding loop, so you control the layout entirely (heading level,
a table row, whatever you want):

```
{%p for o in observations %}
{{ o.title }}
{{p o.content }}
{%p endfor %}
```

Each item has a plain `title` and rich `content` (paragraphs, code blocks, images —
whatever the observation's own rich text contains). `testing_phases` works identically —
just loop over `testing_phases` instead, with the same `x.title` / `x.content` shape. If
no entries are configured, the loop body simply never runs — nothing renders, no error.

### Inside the finding loop — plain values

| Tag | Value |
|---|---|
| `{{ finding.id }}` | The finding's display ID (e.g. `F001`) |
| `{{ finding.title }}` | Finding title |
| `{{ finding.severity }}` | Severity label (Critical / High / Medium / Low / Informational) |
| `{{ finding.status }}` | Status label (Open / Closed) |
| `{{ finding.cvss_score }}` | CVSS score, or `—` if unset |
| `{{ finding.cvss_vector }}` | CVSS vector string, or `—` if unset |
| `{{ finding.cve_id }}` | CVE ID (e.g. `CVE-2024-12345`), or `—` if unset |
| `{{ finding.classifications }}` | A list of classification tags, e.g. `[OWASP Top 10 2021] A01:2021-Broken Access Control` |
| `{{ finding.affects }}` | A list of affected assets |

`classifications` and `affects` are **lists**, not single strings. Used as a plain
`{{ tag }}` on its own, Jinja prints Python's list representation (`['a', 'b']`) — not what
you want. Loop over them inline instead, either joined in one paragraph:

```
Affects: {% for a in finding.affects %}{{ a }}{% if not loop.last %}, {% endif %}{% endfor %}
```

or as separate bulleted paragraphs, the same way the finding loop itself works:

```
{%p for a in finding.affects %}
{{ a }}
{%p endfor %}
```

(style that inner paragraph with whatever bullet-list style you're using, the same as any
other paragraph.)

### Inside the finding loop — rich content

| Tag | Renders |
|---|---|
| `{{p finding['<slug>'] }}` | One finding's content for that content section (see below) |
| `{{p finding.retest_history }}` | A date/tested-by/result table of retest records — remediation reports only, empty otherwise |

#### Content sections are dynamic

A finding's rich-text fields (vulnerability description, technical details, business
impact, etc.) are admin-configured per deployment via **Finding Structure** — they are not
fixed. The exact set, and each one's slug, can change at any time. **Always check the live
list on the profile's Word (.docx) tab before authoring** — it's generated fresh from
whatever's currently active, not from this document.

As of this writing, a typical deployment's slugs look like:

| Slug | Label |
|---|---|
| `vulnerability-description` | Vulnerability description |
| `business-impact` | Business impact |
| `testing-summary` | Testing summary |
| `technical-details` | Technical details |
| `remediation-testing` | Remediation testing |
| `recommendations` | Recommendations |
| `references` | References |

**Use bracket notation, not dot notation, for these:**

```
{{p finding['technical-details'] }}         ✓ correct
{{p finding.technical-details }}            ✗ wrong — silently breaks
```

This is a hard Jinja rule, not a RedScribe quirk: a slug like `technical-details` contains
a hyphen, and `finding.technical-details` parses as *subtraction* (`finding.technical`
minus `details`), not as one attribute name. Bracket notation with the slug as a quoted
string always works, regardless of what characters the slug contains — use it for every
content-section tag, even ones that happen to only contain underscores.

## Mapping your styles

After uploading, you're taken to a page listing content **roles** — RedScribe fills content
into each role, but the actual look comes from a style you choose from your own document's
style catalog:

| Role | Used for |
|---|---|
| Body paragraph | Default paragraph style for ordinary rich-text content |
| Heading 1 – 6 | Headings that appear inside rich content (rare in practice) |
| Bulleted list item | Bullet-list paragraphs |
| Numbered list item | Numbered-list paragraphs |
| Code block | Each line of a code block — this is the fix for the classic problem of code blocks having nowhere to pick up your template's monospace/shaded formatting |
| Block quote | Quoted paragraphs |
| Image caption | The caption paragraph placed under an embedded image, if the source content has alt text |
| Table (breakdown/checklist/etc.) | The Word table style applied to every generated table |
| Table header cell text | Header-row cell paragraphs in generated tables |
| Inline code | A **character** style for inline code spans within a paragraph |

Leave any role unmapped to fall back to Word's default paragraph style — still readable,
just unstyled. There's no requirement to map every role; map the ones you actually use.

Re-uploading a template clears the previous mapping (a new file's styles may not match the
old names), so re-map after every re-upload.

**Practical tip:** define your styles in Word first — Home tab → Styles pane → New Style —
then place your tags. The style-mapping dropdowns are populated straight from your file's
style catalog, so whatever you name them there is exactly what you'll see to pick from.

## Formatting notes and limitations

- **Marks** (bold/italic/underline/strikethrough) on text within a rich section carry
  through automatically. **Inline code** uses your mapped "Inline code" character style if
  set, else falls back to the profile's configured monospace font. **Highlighted** text
  maps to Word's built-in yellow highlight — arbitrary highlight colors aren't supported.
  **Links** render using Word's built-in "Hyperlink" character style automatically; only
  `http://`, `https://`, and `mailto:` links are ever embedded (anything else is dropped
  as a precaution).
- **Nested bulleted/numbered lists** (a sub-bullet under a bullet) are flattened to one
  indent level — Word's per-level list numbering needs more than a named style can carry.
- **Tables** support merged cells (column/row spans) from the source content, and use
  whichever "Table" style you mapped. Column widths are Word's own auto-sizing — the
  original editor's column-width hints aren't carried over.
- **Images** are sized to fit your page's content width if they'd otherwise overflow it,
  else shown at their natural size.
- No DOCX password protection yet (PDF export has this; DOCX doesn't).

## Validation: what gets caught and when

Uploading a template runs it through a **dry-run render** immediately, against dummy
data — so a broken template is rejected with an error message right away, not discovered
later against a real engagement. This catches:

- The file isn't a real `.docx` at all.
- A missing `{%p endfor %}` / `{%tr endfor %}`, or other malformed loop syntax.
- Any other Jinja/template syntax error.

It does **not** catch: a typo'd tag name that happens to be valid Jinja syntax (it'll just
render blank or literally), or a style name you mapped that gets renamed/deleted from a
later re-upload of the *same* filename — re-check your mapping after any re-upload.

## A starter template

The Word (.docx) tab has a **Download starter template** link — a working example with a
finding loop, a pre-defined code-block style, and the tag patterns described above already
in place. Downloading and adapting it is the fastest way to get something working, rather
than starting from a blank document.

## Worked example

A minimal but complete layout:

```
[Title, centered, large]           {{ cover_title }}
[Subtitle, centered]               {{ client_name }} — {{ reference_number }}
[centered]                         {{ test_type_label }}
[centered]                         {{ classification_label }}
                                    {{p firm_logo }}
[page break]

Heading 1: Document Control
                                    {{p document_control }}

Heading 1: Assessment Team
                                    {{p assessment_team }}

Heading 1: Breakdown of Findings
                                    {{p breakdown_table }}

Heading 1: Testing Methodology / Coverage
                                    {{p checklist_coverage }}
                                    {%p for p in testing_phases %}
Heading 2:                         {{ p.title }}
                                    {{p p.content }}
                                    {%p endfor %}

Heading 1: Observations
                                    {%p for o in observations %}
Heading 2:                         {{ o.title }}
                                    {{p o.content }}
                                    {%p endfor %}

Heading 1: Detailed Findings
                                    {%p for finding in findings %}
[bold]                             {{ finding.id }} — {{ finding.title }}
                                    Severity: {{ finding.severity }}   Status: {{ finding.status }}
                                    CVSS: {{ finding.cvss_score }} ({{ finding.cvss_vector }})   CVE: {{ finding.cve_id }}

Heading 2: Description
                                    {{p finding['vulnerability-description'] }}
Heading 2: Technical Details
                                    {{p finding['technical-details'] }}
Heading 2: Business Impact
                                    {{p finding['business-impact'] }}
Heading 2: Recommendations
                                    {{p finding['recommendations'] }}
Heading 2: Retest History
                                    {{p finding.retest_history }}
                                    {%p endfor %}
```

Give the document real "Heading 1"/"Heading 2" styles (Word's built-ins work fine, or your
own) so Word's native Table of Contents feature — insert one yourself via References →
Table of Contents — can pick them up and update on open, the same way it would in any other
Word document.
