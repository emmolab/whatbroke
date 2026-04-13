import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_default_route() -> tuple[bool, str, str | None, str | None]:
    """Return (has_route, route_str, gateway, iface)."""
    try:
        proc = _run(["ip", "route", "show", "default"], timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            route = proc.stdout.strip().splitlines()[0]
            gateway = None
            iface = None
            parts = route.split()
            for idx, token in enumerate(parts[:-1]):
                if token == "via":
                    gateway = parts[idx + 1]
                elif token == "dev":
                    iface = parts[idx + 1]
            return True, route, gateway, iface
        return False, "no default route configured", None, None
    except Exception as exc:
        return False, str(exc), None, None


def _check_resolver_config() -> tuple[list[str], list[str]]:
    """Return (nameservers, issues)."""
    nameservers = []
    issues = []
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("nameserver "):
                    parts = stripped.split()
                    if len(parts) >= 2:
                        nameservers.append(parts[1])
    except FileNotFoundError:
        issues.append("/etc/resolv.conf missing")
    except Exception as exc:
        issues.append(f"could not read /etc/resolv.conf: {exc}")

    if not nameservers:
        issues.append("no nameserver entries configured")

    return nameservers, issues


def _test_dns_resolution() -> list[tuple[str, str | None, str | None]]:
    """Resolve a few domains. Return list of (domain, resolved_ip, error)."""
    domains = ["example.com", "github.com", "cloudflare.com"]
    results = []
    for domain in domains:
        try:
            ip = socket.gethostbyname(domain)
            results.append((domain, ip, None))
        except Exception as exc:
            results.append((domain, None, str(exc)))
    return results


def _test_outbound_https() -> list[tuple[str, bool, str]]:
    """Perform lightweight HTTPS probes. Return (url, ok, detail)."""
    targets = [
        "https://example.com/",
        "https://github.com/",
    ]
    results = []
    for url in targets:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "whatbroke/0.3"},
            method="HEAD",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                results.append((url, True, f"HTTP {getattr(resp, 'status', 'OK')}"))
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 500:
                results.append((url, True, f"HTTP {exc.code}"))
            else:
                results.append((url, False, f"HTTP {exc.code}"))
        except Exception as exc:
            results.append((url, False, str(exc)))
    return results


def _check_gateway_reachability(gateway: str | None) -> tuple[bool | None, str]:
    """Return (reachable, detail). None means not practical to test here."""
    if not gateway:
        return None, "default route has no explicit gateway"
    if not shutil.which("ping"):
        return None, "ping not available"

    try:
        proc = _run(["ping", "-c", "1", "-W", "2", gateway], timeout=5)
        if proc.returncode == 0:
            return True, gateway
        stderr = proc.stderr.strip() or proc.stdout.strip() or "no reply"
        return False, stderr.splitlines()[0]
    except Exception as exc:
        return False, str(exc)


def _check_firewall() -> dict:
    """Return dict of firewall name → status string."""
    fw = {}
    if shutil.which("ufw"):
        try:
            proc = _run(["ufw", "status"], timeout=5)
            first_line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "unknown"
            fw["ufw"] = first_line
        except Exception:
            pass

    if shutil.which("firewall-cmd"):
        try:
            proc = _run(["firewall-cmd", "--state"], timeout=5)
            fw["firewalld"] = proc.stdout.strip()
        except Exception:
            pass

    if not fw and shutil.which("iptables"):
        try:
            proc = _run(["iptables", "-L", "-n", "--line-numbers"], timeout=5)
            if proc.returncode == 0:
                rules = len([l for l in proc.stdout.splitlines()
                              if l and not l.startswith(('Chain', 'target', 'num'))])
                fw["iptables"] = f"{rules} rules"
        except Exception:
            pass
    return fw


def _check_ntp_sync() -> tuple:
    """Return (synced: bool | None, details: str).
    None means timedatectl not available."""
    if shutil.which("timedatectl"):
        try:
            proc = _run(["timedatectl", "show",
                         "--property=NTPSynchronized,NTPService"], timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                props = {}
                for line in proc.stdout.strip().splitlines():
                    if '=' in line:
                        k, v = line.split('=', 1)
                        props[k.strip()] = v.strip()
                synced = props.get("NTPSynchronized", "").lower() == "yes"
                service = props.get("NTPService", "unknown")
                return synced, f"NTP service: {service}"
            proc = _run(["timedatectl", "status"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if "synchronized" in line.lower():
                        synced = "yes" in line.lower()
                        return synced, line.strip()
        except Exception:
            pass

    if shutil.which("chronyc"):
        try:
            proc = _run(["chronyc", "tracking"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if "System time" in line:
                        m = re.search(r'([\d.]+)\s+seconds', line)
                        if m:
                            offset = float(m.group(1))
                            synced = offset < 1.0
                            return synced, f"chrony offset: {offset:.4f}s"
        except Exception:
            pass

    return None, "NTP check: timedatectl/chronyc not available"


def _check_nic_errors() -> list:
    """Return list of issue strings for NICs with errors or drops."""
    issues = []
    try:
        proc = _run(["ip", "-s", "link"], timeout=10)
        if proc.returncode != 0:
            return issues

        lines = proc.stdout.splitlines()
        current_iface = None
        parsing_rx = False
        parsing_tx = False
        rx_labels = []
        tx_labels = []

        for line in lines:
            stripped = line.strip()
            m = re.match(r'^\d+:\s+(\S+):', stripped)
            if m:
                current_iface = m.group(1).rstrip('@')
                parsing_rx = parsing_tx = False
                rx_labels = tx_labels = []
                continue
            if current_iface in (None, 'lo'):
                continue
            if stripped.startswith('RX:'):
                rx_labels = stripped.split()[1:]
                parsing_rx = True
                parsing_tx = False
                continue
            if stripped.startswith('TX:'):
                tx_labels = stripped.split()[1:]
                parsing_tx = True
                parsing_rx = False
                continue
            if parsing_rx and rx_labels:
                values = stripped.split()
                if len(values) == len(rx_labels):
                    idx_err = rx_labels.index('errors') if 'errors' in rx_labels else -1
                    idx_drop = rx_labels.index('dropped') if 'dropped' in rx_labels else -1
                    rx_err = int(values[idx_err]) if idx_err >= 0 else 0
                    rx_drop = int(values[idx_drop]) if idx_drop >= 0 else 0
                    if rx_err > 0:
                        issues.append(f"{current_iface}: {rx_err} RX errors")
                    if rx_drop > 100:
                        issues.append(f"{current_iface}: {rx_drop} RX drops")
                parsing_rx = False
                continue
            if parsing_tx and tx_labels:
                values = stripped.split()
                if len(values) == len(tx_labels):
                    idx_err = tx_labels.index('errors') if 'errors' in tx_labels else -1
                    tx_err = int(values[idx_err]) if idx_err >= 0 else 0
                    if tx_err > 0:
                        issues.append(f"{current_iface}: {tx_err} TX errors")
                parsing_tx = False
    except Exception:
        pass
    return issues


def check() -> Result:
    """Routing, gateway reachability, DNS sanity, outbound HTTPS, firewall, NTP, NIC errors."""
    details = []
    status = "OK"
    remediation = None

    has_route, route_str, gateway, iface = _check_default_route()
    if has_route:
        details.append(f"Default route: {route_str}")
    else:
        details.append(f"Default route: MISSING — {route_str}")
        status = escalate(status, "CRIT")
        remediation = "ip route add default via <gateway>"

    gateway_ok, gateway_detail = _check_gateway_reachability(gateway if has_route else None)
    if gateway_ok is True:
        label = gateway or gateway_detail
        if iface:
            details.append(f"Gateway reachability: OK ({label} via {iface})")
        else:
            details.append(f"Gateway reachability: OK ({label})")
    elif gateway_ok is False:
        details.append(f"Gateway reachability: FAIL ({gateway or 'unknown gateway'}: {gateway_detail})")
        status = escalate(status, "WARN")
        remediation = remediation or "Check link state, VLANs, and the upstream gateway"
    elif gateway_detail:
        details.append(f"Gateway reachability: skipped ({gateway_detail})")

    nameservers, resolver_issues = _check_resolver_config()
    if nameservers:
        details.append(f"Resolver config: {', '.join(nameservers)}")
    for issue in resolver_issues:
        details.append(f"Resolver config: {issue}")
        status = escalate(status, "CRIT")
        remediation = remediation or "Check /etc/resolv.conf and your resolver service"

    dns_results = _test_dns_resolution()
    failed_dns = [(domain, error) for domain, ip, error in dns_results if ip is None]
    if failed_dns:
        for domain, ip, error in dns_results:
            details.append(f"DNS {domain}: {ip if ip else f'FAIL ({error})'}")
        sev = "CRIT" if len(failed_dns) >= 2 else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Check DNS server reachability and resolver health"
    else:
        details.append("DNS resolution: OK")

    https_results = _test_outbound_https()
    failed_https = [(url, detail) for url, ok, detail in https_results if not ok]
    if failed_https:
        for url, ok, detail in https_results:
            details.append(f"HTTPS {url}: {'OK' if ok else 'FAIL'} ({detail})")
        sev = "BROKE" if len(failed_https) == len(https_results) else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Check outbound 443/TLS reachability, proxy policy, and CA trust"
    else:
        details.append("Outbound HTTPS: OK")

    fw = _check_firewall()
    for name, fw_status in fw.items():
        if "inactive" in fw_status.lower() or "not running" in fw_status.lower():
            details.append(f"Firewall {name}: {fw_status} — DISABLED")
            status = escalate(status, "WARN")
            remediation = remediation or f"Enable firewall: {name} enable"
        else:
            details.append(f"Firewall {name}: {fw_status}")
    if not fw:
        details.append("Firewall: no ufw/firewalld/iptables detected")

    synced, ntp_detail = _check_ntp_sync()
    if synced is False:
        details.append(f"NTP: NOT synchronised — {ntp_detail}")
        status = escalate(status, "WARN")
        remediation = remediation or "Enable NTP: timedatectl set-ntp true"
    elif synced is True:
        details.append(f"NTP: synchronised ({ntp_detail})")
    else:
        details.append(ntp_detail)

    nic_issues = _check_nic_errors()
    for issue in nic_issues:
        details.append(f"NIC: {issue}")
        status = escalate(status, "WARN")
        remediation = remediation or "Check NIC hardware and driver: ethtool <iface>"

    if status == "OK":
        msg = "All networking checks passed"
    else:
        parts = []
        if not has_route:
            parts.append("no default route")
        elif gateway_ok is False:
            parts.append("gateway unreachable")
        if resolver_issues:
            parts.append("resolver config broken")
        if failed_dns:
            parts.append(f"{len(failed_dns)} DNS failures")
        if failed_https:
            parts.append(f"{len(failed_https)}/{len(https_results)} HTTPS probes failed")
        if nic_issues:
            parts.append(f"{len(nic_issues)} NIC error(s)")
        msg = ", ".join(parts) if parts else "networking issues detected"

    return Result(
        name="networking",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
