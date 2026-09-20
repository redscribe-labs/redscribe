# Every string a profile can rename instead of accepting the shipped
# English default — field/column labels baked directly into report_ir
# builders (report titles like "Executive Summary" already come from the
# profile's own template/text blocks, so those aren't here; this covers
# only what used to be a hardcoded Python string literal).
#
# Storage: ReportProfile.labels is a flat {key: "custom text"} dict. A
# missing or blank value falls back to the default below — the same
# "blank means inherit" convention already used for
# empty_cell_background_color and the cover/classification overrides, so
# an untouched profile renders byte-identical to before this existed.
LABEL_DEFAULTS: dict[str, str] = {
    "toc_heading": "Table of Contents",
    "untitled_section": "Untitled section",
    "assessment_team": "Assessment team",
    "testing_methodology_coverage": "Testing Methodology / Coverage",
    "retest_history": "Retest history",
    "finding_severity_rating": "Severity rating",
    "finding_id_row": "Vulnerability/Finding ID",
    "finding_cvss_score": "CVSS score",
    "finding_cvss_vector": "CVSS vector",
    "finding_cve_id": "CVE ID",
    "finding_classification": "Classification",
    "finding_status": "Status",
    "vuln_table_col_id": "ID",
    "vuln_table_col_severity": "Severity",
    "vuln_table_col_title": "Title",
    "vuln_table_col_status": "Status",
    "doc_control_col_stage": "Stage",
    "doc_control_col_date": "Date",
    "doc_control_col_changed_by": "Changed by",
    "doc_control_report_exported": "Report exported",
    "retest_col_date": "Date",
    "retest_col_tested_by": "Tested by",
    "retest_col_result": "Result",
    "checklist_col_code": "Code",
    "checklist_col_item": "Item",
    "checklist_col_status": "Status",
    "checklist_col_linked_findings": "Linked findings",
    "scan_imports": "Scan imports",
    "scan_imports_col_tool": "Tool",
    "scan_imports_col_filename": "File",
    "scan_imports_col_date": "Imported",
    "scan_imports_col_imported_by": "Imported by",
    "scan_imports_col_findings": "Findings produced",
    "severity_critical": "Critical",
    "severity_high": "High",
    "severity_medium": "Medium",
    "severity_low": "Low",
    "severity_informational": "Informational",
    "status_open": "Open",
    "status_closed": "Closed",
}

# UI grouping/order for the profile edit page's Labels tab — (group title,
# [(key, field label shown to the user), ...]).
LABEL_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("General", [
        ("toc_heading", "Table of contents heading"),
        ("untitled_section", "Fallback for a heading with no text"),
        ("assessment_team", "Assessment team section title"),
        ("testing_methodology_coverage", "Checklist coverage section title"),
        ("retest_history", "Retest history subsection title"),
    ]),
    ("Finding details table", [
        ("finding_severity_rating", "\"Severity rating\" row"),
        ("finding_id_row", "\"Vulnerability/Finding ID\" row"),
        ("finding_cvss_score", "\"CVSS score\" row"),
        ("finding_cvss_vector", "\"CVSS vector\" row"),
        ("finding_cve_id", "\"CVE ID\" row"),
        ("finding_classification", "\"Classification\" row (no tags configured)"),
        ("finding_status", "\"Status\" row"),
    ]),
    ("Vulnerabilities table columns", [
        ("vuln_table_col_id", "ID column"),
        ("vuln_table_col_severity", "Severity column"),
        ("vuln_table_col_title", "Title column"),
        ("vuln_table_col_status", "Status column"),
    ]),
    ("Document control table columns", [
        ("doc_control_col_stage", "Stage column"),
        ("doc_control_col_date", "Date column"),
        ("doc_control_col_changed_by", "Changed by column"),
        ("doc_control_report_exported", "\"Report exported\" row label"),
    ]),
    ("Retest history table columns", [
        ("retest_col_date", "Date column"),
        ("retest_col_tested_by", "Tested by column"),
        ("retest_col_result", "Result column"),
    ]),
    ("Checklist coverage table columns", [
        ("checklist_col_code", "Code column"),
        ("checklist_col_item", "Item column"),
        ("checklist_col_status", "Status column"),
        ("checklist_col_linked_findings", "Linked findings column"),
    ]),
    ("Scan imports table", [
        ("scan_imports", "Section title"),
        ("scan_imports_col_tool", "Tool column"),
        ("scan_imports_col_filename", "File column"),
        ("scan_imports_col_date", "Imported column"),
        ("scan_imports_col_imported_by", "Imported by column"),
        ("scan_imports_col_findings", "Findings produced column"),
    ]),
    ("Severity & status names", [
        ("severity_critical", "\"Critical\" severity name"),
        ("severity_high", "\"High\" severity name"),
        ("severity_medium", "\"Medium\" severity name"),
        ("severity_low", "\"Low\" severity name"),
        ("severity_informational", "\"Informational\" severity name"),
        ("status_open", "\"Open\" finding status name"),
        ("status_closed", "\"Closed\" finding status name"),
    ]),
]


def get_label(profile, key: str) -> str:
    if profile is not None:
        custom = (getattr(profile, "labels", None) or {}).get(key)
        if custom:
            return custom
    return LABEL_DEFAULTS[key]


def get_severity_label(profile, severity: str) -> str:
    """Renamable equivalent of Finding.Severity's display name — severity
    values (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL) are the one vocabulary
    that appears in literally every finding, the breakdown table, and the
    breakdown chart, so unlike most report content (which is free text a
    report author already controls) this was a hardcoded-English ceiling a
    Report Profile couldn't get past. get_FOO_display() intentionally
    isn't used here — that always returns Finding.Severity's own English
    choice label, with no per-profile override hook."""
    return get_label(profile, f"severity_{severity.lower()}")


def get_status_label(profile, status: str) -> str:
    """Same as get_severity_label, for Finding.Status (OPEN/CLOSED)."""
    return get_label(profile, f"status_{status.lower()}")
