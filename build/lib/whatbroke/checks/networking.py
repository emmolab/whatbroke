import re
import shutil
import socket
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_default_route() -> tuple:
    """Return (has_route: bool, route_str: str)."""
    try:
        proc = _run(["ip", "route", "show", "default"], timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            return True, proc.stdout.strip().splitlines()[0]
        return False, "no default route configured"
    except Exception as exc:
        return False, str(exc)


def _test_internet_connectivity() -> list:
    """Ping a handful of well-known IPs. Return list of (host, ok: bool)."""
    targets = [
        ("8.8.8.8",   "Google DNS"),
        ("1.1.1.1",   "Cloudflare DNS"),
        ("9.9.9.9",   "Quad9 DNS"),
    ]
    results = []
    for ip, label in targets:
        try:
            proc = _run(["ping", "-c", "1", "-W", "2", ip], timeout=5)
            results.append((ip, label, proc.returncode == 0))
        except Exception:
            results.append((ip, label, False))
    return results


def _test_dns_resolution() -> list:
    """Resolve a few domains. Return list of (domain, resolved_ip or None)."""
    domains = ["google.com", "example.com", "github.com"]
    results = []
    for domain in domains:
        try:
            ip = socket.gethostbyname(domain)
            results.append((domain, ip))
        except Exception:
            results.append((domain, None))
    return results


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
    # Prefer machine-readable output (systemd 239+)
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
                synced  = props.get("NTPSynchronized", "").lower() == "yes"
                service = props.get("NTPService", "unknown")
                return synced, f"NTP service: {service}"
            # Fall back to human-readable status
            proc = _run(["timedatectl", "status"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if "synchronized" in line.lower():
                        synced = "yes" in line.lower()
                        return synced, line.strip()
        except Exception:
            pass

    # chrony fallback
    if shutil.which("chronyc"):
        try:
            proc = _run(["chronyc", "tracking"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if "System time" in line:
                        # "System time     : 0.000123 seconds slow of NTP time"
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
        # State machine: track which interface we're in, then parse RX/TX stats
        # ip -s link output blocks:
        #   N: eth0: <flags> ...
        #       link/ether ...
        #       RX: bytes  packets  errors  dropped  missed  mcast
        #           NNN    NNN      NNN     NNN      NNN     NNN
        #       TX: bytes  packets  errors  dropped  carrier collsns
        #           NNN    NNN      NNN     NNN      NNN     NNN
        parsing_rx = False
        parsing_tx = False
        rx_labels = []
        tx_labels = []

        for line in lines:
            stripped = line.strip()
            # New interface block
            m = re.match(r'^\d+:\s+(\S+):', stripped)
            if m:
                current_iface = m.group(1).rstrip('@')
                parsing_rx = parsing_tx = False
                rx_labels = tx_labels = []
                continue
            if current_iface in (None, 'lo'):
                continue
            # RX/TX label lines
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
            # Data lines following a label line
            if parsing_rx and rx_labels:
                values = stripped.split()
                if len(values) == len(rx_labels):
                    idx_err  = rx_labels.index('errors')  if 'errors'  in rx_labels else -1
                    idx_drop = rx_labels.index('dropped') if 'dropped' in rx_labels else -1
                    rx_err   = int(values[idx_err])  if idx_err  >= 0 else 0
                    rx_drop  = int(values[idx_drop]) if idx_drop >= 0 else 0
                    if rx_err > 0:
                        issues.append(f"{current_iface}: {rx_err} RX errors")
                    if rx_drop > 100:
                        issues.append(f"{current_iface}: {rx_drop} RX drops")
                parsing_rx = False
                continue
            if parsing_tx and tx_labels:
                values = stripped.split()
                if len(values) == len(tx_labels):
                    idx_err  = tx_labels.index('errors')  if 'errors'  in tx_labels else -1
                    tx_err   = int(values[idx_err]) if idx_err >= 0 else 0
                    if tx_err > 0:
                        issues.append(f"{current_iface}: {tx_err} TX errors")
                parsing_tx = False
    except Exception:
        pass
    return issues


def check() -> Result:
    """Routing, internet reachability, DNS, firewall, NTP sync, NIC errors."""
    details = []
    status  = "OK"
    remediation = None

    # Default route
    has_route, route_str = _check_default_route()
    if has_route:
        details.append(f"Default route: {route_str}")
    else:
        details.append(f"Default route: MISSING — {route_str}")
        status = escalate(status, "CRIT")
        remediation = "ip route add default via <gateway>"

    # Internet connectivity
    conn_results = _test_internet_connectivity()
    failed_hosts = [(ip, lbl) for ip, lbl, ok in conn_results if not ok]
    if failed_hosts:
        for ip, lbl, ok in conn_results:
            details.append(f"Ping {ip} ({lbl}): {'OK' if ok else 'FAIL'}")
        sev = "CRIT" if len(failed_hosts) >= 2 else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Check upstream connectivity; verify gateway and firewall"
    else:
        details.append("Internet connectivity: OK (3/3 hosts reachable)")

    # DNS resolution
    dns_results = _test_dns_resolution()
    failed_dns  = [(d, ip) for d, ip in dns_results if ip is None]
    if failed_dns:
        for domain, ip in dns_results:
            details.append(f"DNS {domain}: {ip if ip else 'FAIL'}")
        sev = "CRIT" if len(failed_dns) >= 2 else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Check /etc/resolv.conf and DNS server reachability"
    else:
        details.append("DNS resolution: OK")

    # Firewall
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

    # NTP sync
    synced, ntp_detail = _check_ntp_sync()
    if synced is False:
        details.append(f"NTP: NOT synchronised — {ntp_detail}")
        status = escalate(status, "WARN")
        remediation = remediation or "Enable NTP: timedatectl set-ntp true"
    elif synced is True:
        details.append(f"NTP: synchronised ({ntp_detail})")
    else:
        details.append(ntp_detail)

    # NIC errors
    nic_issues = _check_nic_errors()
    for issue in nic_issues:
        details.append(f"NIC: {issue}")
        status = escalate(status, "WARN")
        remediation = remediation or "Check NIC hardware and driver: ethtool <iface>"

    if status == "OK":
        msg = "All networking checks passed"
    else:
        parts = []
        if failed_hosts:
            parts.append(f"{len(failed_hosts)}/{len(conn_results)} hosts unreachable")
        if failed_dns:
            parts.append(f"{len(failed_dns)} DNS failures")
        if not has_route:
            parts.append("no default route")
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
