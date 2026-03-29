import os
import shutil
import subprocess
from datetime import datetime, timezone

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_failed_logins() -> tuple:
    """Return (count, sample_lines)."""
    for log in ("/var/log/auth.log", "/var/log/secure"):
        if not os.path.exists(log):
            continue
        try:
            proc = _run(["tail", "-n", "1000", log], timeout=10)
            if proc.returncode != 0:
                continue
            failures = [
                l for l in proc.stdout.splitlines()
                if "failed" in l.lower() or "authentication failure" in l.lower()
            ]
            return len(failures), failures[:10]
        except Exception:
            pass
    return 0, []


def _check_updates() -> dict:
    """Return dict: {'count': N, 'has_security': bool}."""
    if shutil.which("apt"):
        try:
            proc = _run(
                ["bash", "-c", "apt list --upgradable 2>/dev/null | tail -n +2"],
                timeout=30,
            )
            pkgs = [l for l in proc.stdout.splitlines() if l.strip()]
            if pkgs:
                return {
                    'count':        len(pkgs),
                    'has_security': any("security" in p.lower() for p in pkgs),
                }
        except Exception:
            pass

    for tool in ("dnf", "yum"):
        if shutil.which(tool):
            try:
                proc = _run([tool, "check-update"], timeout=30)
                if proc.returncode == 100:
                    pkgs = [
                        l for l in proc.stdout.splitlines()
                        if l.strip() and not l.startswith(("Last metadata", "Obsoleting"))
                    ]
                    return {'count': len(pkgs), 'has_security': False}
            except Exception:
                pass
    return {}


def _check_ssh_config() -> list:
    """Return list of insecure SSH setting names."""
    issues = []
    cfg = "/etc/ssh/sshd_config"
    if not os.path.exists(cfg):
        return issues
    try:
        with open(cfg) as f:
            for line in f:
                l = line.strip().lower()
                if not l or l.startswith("#"):
                    continue
                if l == "permitrootlogin yes":
                    issues.append("root-login")
                if l in ("passwordauthentication yes",
                         "passwordauthentication  yes"):
                    issues.append("password-auth")
    except Exception:
        pass
    return issues


def _check_firewall() -> list:
    """Return list of disabled-firewall issue strings."""
    issues = []
    if shutil.which("ufw"):
        try:
            proc = _run(["ufw", "status"], timeout=5)
            if "inactive" in proc.stdout.lower():
                issues.append("ufw-inactive")
        except Exception:
            pass

    if shutil.which("firewall-cmd"):
        try:
            proc = _run(["firewall-cmd", "--state"], timeout=5)
            if "not running" in proc.stdout.lower():
                issues.append("firewalld-stopped")
        except Exception:
            pass
    return issues


def _check_expiring_certs() -> list:
    """Return list of (path, days_remaining) for expiring/expired certs."""
    issues = []
    now = datetime.now(timezone.utc)
    cert_dirs = (
        "/etc/ssl/certs",
        "/etc/pki/tls/certs",
        "/etc/letsencrypt/live",
    )
    if not shutil.which("openssl"):
        return issues

    for base in cert_dirs:
        if not os.path.exists(base):
            continue
        try:
            proc = _run(
                ["find", base, "-maxdepth", "3", "-type", "f",
                 "(", "-name", "*.pem", "-o", "-name", "*.crt", ")"],
                timeout=10,
            )
            for cert in proc.stdout.splitlines()[:20]:
                cert = cert.strip()
                if not cert:
                    continue
                try:
                    c = _run(
                        ["openssl", "x509", "-in", cert, "-noout", "-enddate"],
                        timeout=5,
                    )
                    if c.returncode != 0:
                        continue
                    date_str = c.stdout.split("=", 1)[1].strip()
                    exp = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                    exp = exp.replace(tzinfo=timezone.utc)
                    days = (exp - now).days
                    if days < 0:
                        issues.append((cert, days))   # expired
                    elif days <= 30:
                        issues.append((cert, days))   # expiring soon
                except Exception:
                    pass
        except Exception:
            pass
    return issues


def _check_selinux_apparmor() -> list:
    """Return list of MAC (SELinux/AppArmor) issue strings."""
    issues = []
    # SELinux
    if shutil.which("getenforce"):
        try:
            proc = _run(["getenforce"], timeout=5)
            mode = proc.stdout.strip()
            if mode == "Disabled":
                issues.append("SELinux: Disabled — mandatory access control not enforced")
            elif mode == "Permissive":
                issues.append("SELinux: Permissive — only logging, not enforcing")
            # Enforcing is fine; no issue added
        except Exception:
            pass

    # AppArmor
    if shutil.which("aa-status"):
        try:
            proc = _run(["aa-status", "--enabled"], timeout=5)
            if proc.returncode != 0:
                issues.append("AppArmor: not enabled")
            else:
                # Count enforced profiles
                proc2 = _run(["aa-status", "--json"], timeout=5)
                if proc2.returncode == 0:
                    import json as _json
                    data = _json.loads(proc2.stdout)
                    enforced = data.get("profiles", {}).get("enforce", 0)
                    if isinstance(enforced, dict):
                        enforced = len(enforced)
                    if enforced == 0:
                        issues.append("AppArmor: loaded but 0 profiles in enforce mode")
        except Exception:
            pass
    return issues


def _check_entropy() -> tuple:
    """Return (entropy_avail: int | None, issue: bool)."""
    try:
        with open("/proc/sys/kernel/random/entropy_avail") as f:
            avail = int(f.read().strip())

        # On Linux 5.17+ the DRBG always reads 256; no meaningful threshold
        import platform
        kern = platform.release().split('.')
        try:
            major, minor = int(kern[0]), int(kern[1])
            if major > 5 or (major == 5 and minor >= 17):
                return avail, False   # new DRBG — value always high
        except (ValueError, IndexError):
            pass

        return avail, avail < 200
    except Exception:
        return None, False


def check() -> Result:
    """Failed logins, pending updates, SSH config, firewall, certificates,
    SELinux/AppArmor, entropy pool."""
    details = []
    status  = "OK"
    remediation = None

    # Failed logins
    failed_logins, login_samples = _check_failed_logins()
    if failed_logins > 20:
        details.append(f"Failed logins: {failed_logins} in recent auth log — HIGH")
        for sample in login_samples[:5]:
            details.append(f"  {sample}")
        status = escalate(status, "WARN")
    elif failed_logins > 5:
        details.append(f"Failed logins: {failed_logins} in recent auth log")
        status = escalate(status, "WARN")
    else:
        details.append(f"Failed logins: {failed_logins} (normal)")

    # Pending updates
    updates = _check_updates()
    if updates:
        count = updates['count']
        has_sec = updates.get('has_security', False)
        if has_sec:
            details.append(f"Updates: {count} packages pending — SECURITY updates available")
            status = escalate(status, "WARN")
            remediation = "Apply security updates: apt upgrade / dnf update --security"
        else:
            details.append(f"Updates: {count} packages pending")
            status = escalate(status, "WARN")
            remediation = remediation or "Apply updates: apt upgrade / dnf update"
    else:
        details.append("Updates: system up to date")

    # SSH configuration
    ssh_issues = _check_ssh_config()
    if "root-login" in ssh_issues:
        details.append("SSH: root login permitted — INSECURE")
        status = escalate(status, "WARN")
        remediation = remediation or "Set PermitRootLogin no in /etc/ssh/sshd_config"
    if "password-auth" in ssh_issues:
        details.append("SSH: password authentication enabled (prefer key-based auth)")
        status = escalate(status, "WARN")
    if not ssh_issues:
        details.append("SSH: configuration looks secure")

    # Firewall
    fw_issues = _check_firewall()
    if fw_issues:
        for issue in fw_issues:
            if issue == "ufw-inactive":
                details.append("Firewall: UFW inactive — host is unprotected")
            elif issue == "firewalld-stopped":
                details.append("Firewall: firewalld not running — host is unprotected")
            else:
                details.append(f"Firewall: {issue}")
        status = escalate(status, "WARN")
        remediation = remediation or "Enable firewall: ufw enable / systemctl start firewalld"
    else:
        if shutil.which("ufw") or shutil.which("firewall-cmd"):
            details.append("Firewall: active")
        else:
            details.append("Firewall: no ufw/firewalld detected (check iptables manually)")

    # SSL/TLS certificates
    cert_issues = _check_expiring_certs()
    for cert_path, days in cert_issues:
        if days < 0:
            details.append(f"Certificate EXPIRED: {cert_path}")
            status = escalate(status, "CRIT")
            remediation = remediation or "Renew expired certificate immediately"
        else:
            details.append(f"Certificate expires in {days}d: {cert_path}")
            status = escalate(status, "WARN")
            remediation = remediation or "Renew certificate: certbot renew / acme.sh renew"
    if not cert_issues:
        details.append("Certificates: none expiring within 30 days")

    # SELinux / AppArmor
    mac_issues = _check_selinux_apparmor()
    for issue in mac_issues:
        details.append(issue)
        status = escalate(status, "WARN")

    # Entropy pool
    entropy, low_entropy = _check_entropy()
    if entropy is not None:
        if low_entropy:
            details.append(f"Entropy pool: {entropy} bits — LOW (crypto operations may block)")
            status = escalate(status, "WARN")
            remediation = remediation or "Install rng-tools or haveged to improve entropy"
        else:
            details.append(f"Entropy pool: {entropy} bits")

    # Build message
    if status == "OK":
        msg = "Security checks passed"
    else:
        parts = []
        if failed_logins > 5:
            parts.append(f"{failed_logins} failed logins")
        if updates:
            parts.append(f"{updates['count']} updates pending"
                         + (" (security)" if updates.get('has_security') else ""))
        if ssh_issues:
            parts.append("SSH misconfigured")
        if fw_issues:
            parts.append("firewall down")
        if cert_issues:
            parts.append(f"{len(cert_issues)} cert issue(s)")
        if mac_issues:
            parts.append("MAC policy issue")
        msg = "; ".join(parts) if parts else "security issues detected"

    return Result(
        name="security",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
