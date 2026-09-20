import re

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .base import ImportedFinding

_VULN_MARKER_RE = re.compile(r"State:\s*VULNERABLE", re.IGNORECASE)
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}")


def parse(raw) -> list[ImportedFinding]:
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ValueError(f"Invalid Nmap XML: {exc}") from exc
    if root.tag != "nmaprun":
        raise ValueError("Not an Nmap XML report (root element must be <nmaprun> — use nmap -oX).")

    results = []
    for host in root.findall("host"):
        address_el = host.find("address")
        host_ip = address_el.get("addr") if address_el is not None else "unknown host"
        hostname_el = host.find("hostnames/hostname")
        hostname = hostname_el.get("name") if hostname_el is not None else ""
        label = f"{hostname} ({host_ip})" if hostname else host_ip

        ports_el = host.find("ports")
        if ports_el is None:
            continue
        for port in ports_el.findall("port"):
            state_el = port.find("state")
            if state_el is None or state_el.get("state") != "open":
                continue

            portid = port.get("portid", "?")
            protocol = port.get("protocol", "tcp")
            service_el = port.find("service")
            service_name = service_el.get("name", "unknown") if service_el is not None else "unknown"
            product = service_el.get("product", "") if service_el is not None else ""
            version = service_el.get("version", "") if service_el is not None else ""
            service_desc = " ".join(p for p in [product, version] if p)

            vuln_scripts = [
                (script.get("id", "script"), script.get("output", ""))
                for script in port.findall("script")
                if _VULN_MARKER_RE.search(script.get("output", ""))
            ]

            if vuln_scripts:
                for script_id, output in vuln_scripts:
                    cve_match = _CVE_RE.search(output)
                    results.append(ImportedFinding(
                        title=f"{script_id} on {portid}/{protocol} ({label})",
                        severity="HIGH",
                        affects=f"{host_ip}:{portid}/{protocol}",
                        technical_details=(
                            f"Detected by Nmap NSE script '{script_id}' against {label}.\n\n{output}"
                        ),
                        cve_id=cve_match.group(0) if cve_match else "",
                        tags=["Vulnerability Script"],
                    ))
            else:
                results.append(ImportedFinding(
                    title=f"Open port {portid}/{protocol} ({service_name}) on {label}",
                    severity="INFORMATIONAL",
                    affects=f"{host_ip}:{portid}/{protocol}",
                    technical_details=f"Service: {service_name}\nProduct/version: {service_desc or 'unknown'}",
                    tags=["Open Port"],
                ))

    if not results:
        raise ValueError("No open ports found in this Nmap report.")
    return results
