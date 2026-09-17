from dataclasses import dataclass, field


@dataclass
class ImportedFinding:
    title: str
    severity: str
    affects: str = ""
    technical_details: str = ""
    cve_id: str = ""
    tags: list = field(default_factory=list)
