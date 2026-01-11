import os
import shutil
import subprocess
from datetime import datetime

from whatbroke.result import Result


# ---------------------------
# Helpers
# ---------------------------

def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _firewall_restricts_ssh():
    if shutil.which("ufw"):
        r = _run(["ufw", "status"])
        if r.returncode == 0 and "22" in r.stdout:
            return True

    if shutil.which("firewall-cmd"):
        r = _run(["firewall-cmd", "--list-services"])
        if r.returncode == 0 and "ssh" in r.stdout:
            return True

    if shutil.which("iptables"):
        r = _run(["iptables", "-L", "-n"])
        if r.returncode == 0 and "dpt:22" in r.stdout:
            return True

    return False


# ---------------------------
# Checks
# ---------------------------

def _check_failed_logins():
    log = "/var/log/auth.log"
    if not os.path.exists(log):
        log = "/var/log/secure"

    if not os.path.exists(log):
        return 0, []

    r = _run(["tail", "-n", "1000", log])
    if r.returncode != 0:
        return 0, []

    failures = [
        l for l in r.stdout.splitlines()
        if "failed" in l.lower() or "authentication failure" in l.lower()
    ]

    return len(failures), failures[:10]


def _check_updates():
    info = []

    if shutil.which("apt"):
        r = _run(["bash", "-c", "apt list --upgradable 2>/dev/null | tail -n +2"])
        pkgs = [l for l in r.stdout.splitlines() if l.strip()]
        if pkgs:
            info.append(f"count={len(pkgs)}")
            if any("security" in p.lower() for p in pkgs):
                info.append("security")

    for tool in ("dnf", "yum"):
        if shutil.which(tool):
            r = _run([tool, "check-update"])
            if r.returncode == 100:
                lines = [
                    l for l in r.stdout.splitlines()
                    if l and not l.startswith(("Last metadata", "Obsoleting"))
                ]
                info.append(f"count={len(lines)}")

    return info


def _check_ssh():
    if _firewall_restricts_ssh():
        return []

    issues = []
    cfg = "/etc/ssh/sshd_config"
    if not os.path.exists(cfg):
        return issues

    with open(cfg) as f:
        for line in f:
            l = line.strip().lower()
            if not l or l.startswith("#"):
                continue
            if l == "permitrootlogin yes":
                issues.append("root-login")
            if l == "passwordauthentication yes":
                issues.append("password-auth")

    return issues


def _check_firewall():
    if shutil.which("ufw"):
        r = _run(["ufw", "status"])
        if "inactive" in r.stdout.lower():
            return ["ufw-inactive"]

    if shutil.which("firewall-cmd"):
        r = _run(["firewall-cmd", "--state"])
        if "not running" in r.stdout.lower():
            return ["firewalld-stopped"]

    return []


def _check_certs():
    issues = []
    now = datetime.utcnow()

    cert_dirs = (
        "/etc/ssl/certs",
        "/etc/pki/tls/certs",
        "/etc/letsencrypt/live",
    )

    for base in cert_dirs:
        if not os.path.exists(base):
            continue

        r = _run([
            "find", base,
            "-type", "f",
            "(",
            "-name", "*.pem",
            "-o", "-name", "*.crt",
            ")"
        ])

        if r.returncode != 0:
            continue

        for cert in r.stdout.splitlines()[:20]:
            c = _run(["openssl", "x509", "-in", cert, "-noout", "-enddate"])
            if c.returncode != 0:
                continue

            try:
                date = c.stdout.split("=", 1)[1].strip()
                exp = datetime.strptime(date, "%b %d %H:%M:%S %Y %Z")
                days = (exp - now).days

                if days < 0:
                    issues.append(f"{cert}: expired")
                elif days <= 30:
                    issues.append(f"{cert}: {days}d")

            except Exception:
                continue

    return issues


# ---------------------------
# Entry
# ---------------------------

def check():
    details = []
    status = "OK"
    remediation = None

    failed, samples = _check_failed_logins()
    if failed > 5:
        if status != "CRIT":
            status = "WARN"
        details.append(f"High number of failed login attempts: {failed} in recent logs")
        details.extend([f"  {sample}" for sample in samples[:5]])

    updates = _check_updates()
    if updates:
        if status != "CRIT":
            status = "WARN"
        update_msgs = []
        for item in updates:
            if item.startswith("count="):
                count = item.split("=")[1]
                update_msgs.append(f"{count} packages available for update")
            elif item == "security":
                update_msgs.append("Security updates available")
            else:
                update_msgs.append(item)
        details.append("System updates: " + ", ".join(update_msgs))
        if not remediation:
            remediation = "apply updates"

    ssh = _check_ssh()
    if ssh:
        status = "WARN"
        ssh_issues = []
        for issue in ssh:
            if issue == "root-login":
                ssh_issues.append("SSH allows root login")
            elif issue == "password-auth":
                ssh_issues.append("SSH allows password authentication")
            else:
                ssh_issues.append(f"SSH issue: {issue}")
        details.extend(ssh_issues)

    fw = _check_firewall()
    if fw:
        status = "CRIT"
        fw_issues = []
        for issue in fw:
            if issue == "ufw-inactive":
                fw_issues.append("UFW firewall is inactive")
            elif issue == "firewalld-stopped":
                fw_issues.append("firewalld service is not running")
            else:
                fw_issues.append(f"Firewall issue: {issue}")
        details.extend(fw_issues)
        remediation = "enable firewall"

    certs = _check_certs()
    if certs:
        if status != "CRIT":
            status = "WARN"
        cert_issues = []
        for cert in certs:
            if ": expired" in cert:
                cert_issues.append(f"Certificate expired: {cert.split(':')[0]}")
            elif "d" in cert:
                days = cert.split(':')[1].strip()
                cert_issues.append(f"Certificate expires in {days}: {cert.split(':')[0]}")
            else:
                cert_issues.append(f"Certificate issue: {cert}")
        details.extend(cert_issues)

    if status == "OK":
        # Provide detailed security information for OK status
        details = []
        status_parts = []
        
        # Check failed logins
        failed, samples = _check_failed_logins()
        if failed == 0:
            status_parts.append("no failed logins")
            details.append("Recent authentication logs: No failures detected")
        elif failed <= 5:
            status_parts.append(f"minimal failed logins ({failed})")
            details.append(f"Recent authentication logs: {failed} failed attempts (within normal range)")
        
        # Check updates
        updates = _check_updates()
        if not updates:
            status_parts.append("system up to date")
            details.append("System packages: All up to date")
        
        # Check SSH security
        ssh_issues = _check_ssh()
        if not ssh_issues:
            status_parts.append("SSH secure")
            # Add SSH configuration details
            cfg = "/etc/ssh/sshd_config"
            if os.path.exists(cfg):
                with open(cfg) as f:
                    for line in f:
                        l = line.strip().lower()
                        if not l or l.startswith("#"):
                            continue
                        if l.startswith("permitrootlogin"):
                            if "no" in l:
                                details.append("SSH: Root login disabled")
                        elif l.startswith("passwordauthentication"):
                            if "no" in l:
                                details.append("SSH: Password authentication disabled (key-based only)")
                        elif l.startswith("port"):
                            port = l.split()[1]
                            if port != "22":
                                details.append(f"SSH: Running on non-standard port {port}")
        
        # Check firewall
        fw_issues = _check_firewall()
        if not fw_issues:
            status_parts.append("firewall active")
            if shutil.which("ufw"):
                r = _run(["ufw", "status"])
                if "active" in r.stdout.lower():
                    details.append("Firewall: UFW active and configured")
            elif shutil.which("firewall-cmd"):
                r = _run(["firewall-cmd", "--state"])
                if "running" in r.stdout.lower():
                    details.append("Firewall: firewalld active and running")
        
        # Check certificates
        cert_issues = _check_certs()
        if not cert_issues:
            status_parts.append("certificates valid")
            # Count certificates found
            cert_count = 0
            cert_dirs = (
                "/etc/ssl/certs",
                "/etc/pki/tls/certs",
                "/etc/letsencrypt/live",
            )
            for base in cert_dirs:
                if os.path.exists(base):
                    r = _run([
                        "find", base,
                        "-type", "f",
                        "(",
                        "-name", "*.pem",
                        "-o", "-name", "*.crt",
                        ")",
                        "-exec", "echo", "{}", ";"
                    ])
                    if r.returncode == 0:
                        cert_count += len([l for l in r.stdout.splitlines() if l.strip()])
            
            if cert_count > 0:
                details.append(f"Certificates: {cert_count} certificates found, all valid")
            else:
                details.append("Certificates: No certificates found")
        
        return Result(
            name="security",
            status="OK", 
            message="Security checks passed", 
            details=details
        )

    return Result(
        name="security",
        status=status,
        message="issues",
        details=details,
        remediation=remediation,
    )
