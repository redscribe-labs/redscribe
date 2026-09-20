PERMISSIONS = [
    (
        "engagements.create",
        "Create engagements",
        "Engagements",
    ),
    (
        "engagements.manage",
        "Manage engagement membership, metadata, and scope-change approval "
        "(non-archived engagements)",
        "Engagements",
    ),
    (
        "engagements.view_all",
        "View every non-archived engagement without needing explicit membership",
        "Engagements",
    ),
    (
        "engagements.release_to_client",
        "Approve releasing an engagement's findings to the client portal",
        "Engagements",
    ),
    (
        "catalogue.manage",
        "Create, edit, and delete vulnerability catalogue templates",
        "Catalogue",
    ),
    (
        "catalogue.approve",
        "Approve draft vulnerability catalogue entries",
        "Catalogue",
    ),
    (
        "catalogue.delete_any",
        "Delete any catalogue entry, including ones created by someone else",
        "Catalogue",
    ),
    (
        "catalogue.bulk_manage",
        "Export/import the whole vulnerability catalogue at once",
        "Catalogue",
    ),
    (
        "checklist_templates.manage",
        "Manage checklist templates",
        "Checklist",
    ),
    (
        "report_settings.manage",
        "Manage report profiles and export settings",
        "Reports",
    ),
    (
        "reports.trends",
        "View cross-engagement trend reporting (severity over time, mean time to remediate, "
        "repeat findings by client)",
        "Reports",
    ),
    (
        "findings.review",
        "Review findings (eligible to be assigned as reviewer)",
        "Finding Review",
    ),
    (
        "findings.review_own",
        "Review findings authored by yourself",
        "Finding Review",
    ),
    (
        "findings.qa",
        "QA findings (eligible to be assigned as QA reviewer)",
        "Finding Review",
    ),
    (
        "findings.qa_own",
        "QA findings authored by yourself",
        "Finding Review",
    ),
    (
        "findings.act_any_assignment",
        "Submit any finding's review/QA decision, regardless of who it's assigned to",
        "Finding Review",
    ),
    (
        "clients.manage",
        "Manage client-portal companies and accounts",
        "Client Portal",
    ),
    (
        "users.manage",
        "⚠ Manage user accounts (create, deactivate, change roles). Someone holding this can also "
        "grant themselves roles.manage and become Superadmin-equivalent — see this category's own warning.",
        "Administration",
    ),
    (
        "roles.manage",
        "⚠ Manage roles and permissions, including this list. Someone holding this can grant themselves "
        "(or anyone) every permission here — effectively Superadmin-equivalent.",
        "Administration",
    ),
    (
        "feature_flags.manage",
        "Manage feature flags",
        "Administration",
    ),
    (
        "licensing.manage",
        "Manage the license key",
        "Administration",
    ),
    (
        "audit_log.manage",
        "View and purge the audit log",
        "Administration",
    ),
    (
        "field_visibility.manage",
        "Manage which finding/catalogue fields are visible",
        "Administration",
    ),
    (
        "branding.manage",
        "Manage firm branding (name, logo) shown on the login page, sidebar, and reports",
        "Administration",
    ),
]

DEFAULT_ROLE_PERMISSIONS = {
    "team_lead": {
        "engagements.create",
        "engagements.manage",
        "engagements.view_all",
        "engagements.release_to_client",
        "catalogue.manage",
        "catalogue.approve",
        "catalogue.delete_any",
        "findings.review",
        "findings.review_own",
        "findings.qa",
        "findings.qa_own",
        "reports.trends",
        "checklist_templates.manage",
        "clients.manage",
    },
    "senior": {
        "findings.review",
        "findings.qa",
        "catalogue.approve",
    },
    "consultant": set(),
}
