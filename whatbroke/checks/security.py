import os
import shutil
import subprocess
from datetime import datetime, timezone

from ..result import Result, escalate

_FAILED_LOGIN_WARN = 20
_FAILED_LOGIN_CRIT = 100
_PENDING_UPDATE_WARN = 25
_PENDING_UPDATE_BROKE = 100


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
                    "count": len(pkgs),
                    "has_security": any("security" in p.lower() for p in pkgs),
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
                    return {"count": len(pkgs), "has_security": False}
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
                if l in ("passwordauthentication yes", "passwordauthentication  yes"):
                    issues.append("password-auth")
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
                [
                    "find",
                    base,
                    "-maxdepth",
                    "3",
                    "-type",
                    "f",
                    "(",
                    "-name",
                    "*.pem",
                    "-o",
                    "-name",
                    "*.crt",
                    ")",
                ],
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
                        issues.append((cert, days))
                    elif days <= 30:
                        issues.append((cert, days))
                except Exception:
                    pass
        except Exception:
            pass
    return issues


def _check_selinux_apparmor() -> list:
    """Return list of MAC (SELinux/AppArmor) issue strings."""
    issues = []
    if shutil.which("getenforce"):
        try:
            proc = _run(["getenforce"], timeout=5)
            mode = proc.stdout.strip()
            if mode == "Disabled":
                issues.append("SELinux: Disabled — mandatory access control not enforced")
            elif mode == "Permissive":
                issues.append("SELinux: Permissive — logging only, not enforcing")
        except Exception:
            pass

    if shutil.which("aa-status"):
        try:
            proc = _run(["aa-status", "--enabled"], timeout=5)
            if proc.returncode != 0:
                issues.append("AppArmor: not enabled")
            else:
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

        import platform

        kern = platform.release().split(".")
        try:
            major, minor = int(kern[0]), int(kern[1])
            if major > 5 or (major == 5 and minor >= 17):
                return avail, False
        except (ValueError, IndexError):
            pass

        return avail, avail < 200
    except Exception:
        return None, False


def check() -> Result:
    """Failed logins, pending updates, SSH config, certificates,
    SELinux/AppArmor, entropy pool."""
    details = []
    status = "OK"
    remediation_parts = []

    failed_logins, login_samples = _check_failed_logins()
    if failed_logins >= _FAILED_LOGIN_CRIT:
        details.append(f"Failed logins: {failed_logins} in recent auth log — sustained brute-force noise")
        details.extend(f"  {sample}" for sample in login_samples[:5])
        status = escalate(status, "BROKE")
        remediation_parts.append("Review sources with: journalctl -u ssh -S -24h | grep -i 'failed'")
        remediation_parts.append("Consider rate-limiting with fail2ban, sshguard, or upstream filtering")
    elif failed_logins >= _FAILED_LOGIN_WARN:
        details.append(f"Failed logins: {failed_logins} in recent auth log")
        details.extend(f"  {sample}" for sample in login_samples[:3])
        status = escalate(status, "WARN")
    else:
        details.append(f"Failed logins: {failed_logins} in recent auth log window")

    updates = _check_updates()
    if updates:
        count = updates["count"]
        has_sec = updates.get("has_security", False)
        if has_sec:
            details.append(f"Updates: {count} packages pending — security updates available")
            status = escalate(status, "WARN")
            remediation_parts.append("Apply security updates during the next maintenance window")
        elif count >= _PENDING_UPDATE_BROKE:
            details.append(f"Updates: {count} packages pending — patch backlog is large")
            status = escalate(status, "BROKE")
            remediation_parts.append("Schedule a patching window; validate and apply backlog")
        elif count >= _PENDING_UPDATE_WARN:
            details.append(f"Updates: {count} packages pending")
            status = escalate(status, "WARN")
        else:
            details.append(f"Updates: {count} packages pending (informational)")
    else:
        details.append("Updates: no pending packages detected")

    ssh_issues = _check_ssh_config()
    if "root-login" in ssh_issues:
        details.append("SSH: PermitRootLogin yes")
        status = escalate(status, "WARN")
        remediation_parts.append("Set PermitRootLogin prohibit-password or no in /etc/ssh/sshd_config")
    if "password-auth" in ssh_issues:
        details.append("SSH: PasswordAuthentication yes")
        status = escalate(status, "WARN")
        remediation_parts.append("Prefer key-based SSH auth where practical")
    if not ssh_issues:
        details.append("SSH: configuration looks conservative")

    cert_issues = _check_expiring_certs()
    for cert_path, days in cert_issues:
        if days < 0:
            details.append(f"Certificate expired: {cert_path}")
            status = escalate(status, "CRIT")
            remediation_parts.append("Renew the expired certificate immediately")
        else:
            details.append(f"Certificate expires in {days}d: {cert_path}")
            status = escalate(status, "WARN")
            remediation_parts.append("Renew or replace certificates before expiry")
    if not cert_issues:
        details.append("Certificates: none expiring within 30 days")

    mac_issues = _check_selinux_apparmor()
    for issue in mac_issues:
        details.append(issue)
        status = escalate(status, "WARN")
    if mac_issues:
        remediation_parts.append("Review SELinux/AppArmor policy mode against your host hardening baseline")

    entropy, low_entropy = _check_entropy()
    if entropy is not None:
        if low_entropy:
            details.append(f"Entropy pool: {entropy} bits — low on older kernels")
            status = escalate(status, "WARN")
            remediation_parts.append("Install rng-tools or check hardware RNG availability")
        else:
            details.append(f"Entropy pool: {entropy} bits")

    if status == "OK":
        msg = "Security posture looks sane"
    else:
        parts = []
        if failed_logins >= _FAILED_LOGIN_WARN:
            parts.append(f"{failed_logins} failed logins")
        if updates:
            if updates.get("has_security"):
                parts.append(f"{updates['count']} updates pending (security)")
            elif updates["count"] >= _PENDING_UPDATE_WARN:
                parts.append(f"{updates['count']} updates pending")
        if ssh_issues:
            parts.append("SSH policy to review")
        if cert_issues:
            parts.append(f"{len(cert_issues)} cert issue(s)")
        if mac_issues:
            parts.append("MAC policy to review")
        msg = "; ".join(parts) if parts else "security issues detected"

    remediation = "\n".join(dict.fromkeys(remediation_parts)) if status != "OK" and remediation_parts else None

    return Result(
        name="security",
        status=status,
        message=msg,
        details=details,
        remediation=remediation,
    )
