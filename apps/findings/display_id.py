from .models import Finding


def assign_display_ids(findings: list[Finding], prefix: str = "F") -> None:
    for i, finding in enumerate(findings, start=1):
        finding.display_id = f"{prefix}{i:03d}"
