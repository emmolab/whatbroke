import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..result import Result, escalate
from ._packaging import detect_package_kind as _detect_package_kind

_FAILED_LOGIN_WARN = 20
_FAILED_LOGIN_CRIT = 100
_PENDING_UPDATE_WARN = 25
_PENDING_UPDATE_BROKE = 100
_CERT_WARN_DAYS = 30
_CERT_SCAN_LIMIT = 40
_REBOOT_FLAG_PATHS = (
    "/run/reboot-required",
    "/var/run/reboot-required",
)
_REBOOT_PKG_PATHS = (
    "/run/reboot-required.pkgs",
    "/var/run/reboot-required.pkgs",
)


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _is_ssh_failed_login_line(line: str) -> bool:
    lowered = line.lower()
    if not any(marker in lowered for marker in ("sshd", "dropbear")):
        return False
    return any(
        marker in lowered
        for marker in (
            "failed password",
            "failed publickey",
            "authentication failure",
            "invalid user",
            "maximum authentication attempts exceeded",
        )
    )



def _check_failed_logins_from_auth_logs() -> tuple[int, list[str]] | None:
    """Return recent SSH failed-logins from classic auth logs, if available."""
    for log in ("/var/log/auth.log", "/var/log/secure"):
        if not os.path.exists(log):
            continue
        try:
            proc = _run(["tail", "-n", "1000", log], timeout=10)
            if proc.returncode != 0:
                continue
            failures = [
                line for line in proc.stdout.splitlines()
                if _is_ssh_failed_login_line(line)
            ]
            return len(failures), failures[:10]
        except Exception:
            pass
    return None


def _check_failed_logins_from_journal() -> tuple[int, list[str]]:
    """Return recent SSH failed-logins from journald for journal-only hosts."""
    try:
        proc = _run(
            [
                "journalctl",
                "--since",
                "24 hours ago",
                "--no-pager",
                "--output=short",
                "-q",
                "-t",
                "sshd",
                "-t",
                "dropbear",
            ],
            timeout=15,
        )
        if proc.returncode == 0:
            failures = [
                line for line in proc.stdout.splitlines()
                if _is_ssh_failed_login_line(line)
            ]
            return len(failures), failures[:10]
    except Exception:
        pass
    return 0, []


def _check_failed_logins() -> tuple:
    """Return recent SSH failed-login count and sample lines."""
    from_logs = _check_failed_logins_from_auth_logs()
    if from_logs is not None:
        return from_logs
    return _check_failed_logins_from_journal()


def _check_updates() -> dict:
    """Return dict: {'count': N, 'has_security': bool}."""
    package_kind = _detect_package_kind()

    if package_kind == "deb" and shutil.which("apt"):
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

    rpm_tools = ("dnf", "yum") if package_kind in {"rpm", None} else ()
    for tool in rpm_tools:
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

    if shutil.which("sshd"):
        try:
            proc = _run(
                [
                    "sshd",
                    "-T",
                    "-f",
                    "/etc/ssh/sshd_config",
                    "-C",
                    "user=root",
                    "-C",
                    "host=localhost",
                    "-C",
                    "addr=127.0.0.1",
                ],
                timeout=10,
            )
            if proc.returncode == 0:
                effective = {}
                for line in proc.stdout.splitlines():
                    stripped = line.strip().lower()
                    if not stripped or " " not in stripped:
                        continue
                    key, value = stripped.split(None, 1)
                    effective[key] = value.strip()
                if effective.get("permitrootlogin") == "yes":
                    issues.append("root-login")
                if effective.get("passwordauthentication") == "yes":
                    issues.append("password-auth")
                return issues
        except Exception:
            pass

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


def _parse_cert_enddate(cert: str):
    c = _run(["openssl", "x509", "-in", cert, "-noout", "-enddate"], timeout=5)
    if c.returncode != 0 or "=" not in c.stdout:
        return None
    date_str = c.stdout.split("=", 1)[1].strip()
    exp = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
    return exp.replace(tzinfo=timezone.utc)


def _certificate_search_roots() -> tuple[str, ...]:
    return (
        "/etc/letsencrypt/live",
        "/etc/ssl/private",
        "/etc/pki/tls/certs",
        "/etc/pki/tls/private",
        "/etc/nginx",
        "/etc/apache2",
        "/etc/httpd",
        "/etc/haproxy",
        "/etc/postfix",
        "/etc/dovecot",
        "/etc/caddy",
        "/etc/traefik",
    )


def _iter_candidate_certificate_paths() -> list[str]:
    seen = set()
    candidates = []
    for base in _certificate_search_roots():
        if not os.path.exists(base):
            continue
        try:
            proc = _run(
                [
                    "find",
                    base,
                    "-maxdepth",
                    "4",
                    "-type",
                    "f",
                    "(",
                    "-name",
                    "*.pem",
                    "-o",
                    "-name",
                    "*.crt",
                    "-o",
                    "-name",
                    "*.cer",
                    ")",
                ],
                timeout=10,
            )
            if proc.returncode != 0:
                continue
            for raw in proc.stdout.splitlines():
                cert = raw.strip()
                if not cert:
                    continue
                name = os.path.basename(cert).lower()
                if name in {"privkey.pem", "chain.pem"}:
                    continue
                real = os.path.realpath(cert)
                if real in seen:
                    continue
                seen.add(real)
                candidates.append(cert)
                if len(candidates) >= _CERT_SCAN_LIMIT:
                    return candidates
        except Exception:
            pass
    return candidates


def _check_expiring_certs() -> list:
    """Return list of (path, days_remaining) for expiring/expired certs."""
    issues = []
    now = datetime.now(timezone.utc)
    if not shutil.which("openssl"):
        return issues

    for cert in _iter_candidate_certificate_paths():
        try:
            exp = _parse_cert_enddate(cert)
            if exp is None:
                continue
            days = (exp - now).days
            if days < 0 or days <= _CERT_WARN_DAYS:
                issues.append((cert, days))
        except Exception:
            pass
    return issues


def _has_certbot_renewal_cron() -> bool:
    cron_paths = (
        Path("/etc/cron.d/certbot"),
        Path("/etc/cron.daily/certbot"),
        Path("/etc/cron.hourly/certbot"),
    )
    for path in cron_paths:
        if not path.exists():
            continue
        try:
            if path.is_dir():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return True
        lowered = content.lower()
        if "certbot" in lowered and "renew" in lowered:
            return True
    return False



def _check_letsencrypt_state() -> dict:
    """Return Let's Encrypt/Certbot context and actionable issues."""
    state = {
        "managed": 0,
        "earliest_days": None,
        "notes": [],
        "issues": [],
        "remediation": [],
    }

    live_dir = Path("/etc/letsencrypt/live")
    renewal_dir = Path("/etc/letsencrypt/renewal")
    renewal_confs = sorted(renewal_dir.glob("*.conf")) if renewal_dir.exists() else []
    live_names = []
    if live_dir.exists():
        for entry in sorted(live_dir.iterdir()):
            if entry.is_dir() and any((entry / name).exists() for name in ("cert.pem", "fullchain.pem")):
                live_names.append(entry.name)
    if live_names:
        state["managed"] = len(live_names)

    if not (live_names or renewal_confs or shutil.which("certbot")):
        return state

    now = datetime.now(timezone.utc)
    earliest = None
    for name in live_names:
        cert_path = live_dir / name / "cert.pem"
        if not cert_path.exists():
            cert_path = live_dir / name / "fullchain.pem"
        if not cert_path.exists():
            continue
        try:
            exp = _parse_cert_enddate(str(cert_path))
            if exp is None:
                continue
            days = (exp - now).days
            earliest = days if earliest is None else min(earliest, days)
        except Exception:
            pass
    state["earliest_days"] = earliest

    if renewal_confs and not shutil.which("certbot"):
        state["issues"].append(
            f"Let's Encrypt: {len(renewal_confs)} renewal config(s) present but certbot is not installed"
        )
        state["remediation"].append("Install certbot or remove stale /etc/letsencrypt renewal configs")
        return state

    if shutil.which("certbot"):
        try:
            proc = _run(["certbot", "certificates"], timeout=20)
            output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            if proc.returncode != 0:
                state["issues"].append("Let's Encrypt: certbot is installed but 'certbot certificates' failed")
                first_error = next((line.strip() for line in output.splitlines() if line.strip()), None)
                if first_error:
                    state["notes"].append(f"  {first_error}")
                state["remediation"].append("Run 'certbot certificates' manually and fix certbot/account state")
            else:
                cert_names = [line.split(":", 1)[1].strip() for line in output.splitlines() if line.strip().startswith("Certificate Name:")]
                if cert_names:
                    state["managed"] = max(state["managed"], len(cert_names))
                valid_days = []
                for line in output.splitlines():
                    m = re.search(r"VALID:\s*(\d+)\s+days", line)
                    if m:
                        valid_days.append(int(m.group(1)))
                if valid_days:
                    parsed_earliest = min(valid_days)
                    state["earliest_days"] = parsed_earliest if state["earliest_days"] is None else min(state["earliest_days"], parsed_earliest)
        except Exception:
            state["issues"].append("Let's Encrypt: unable to query certbot state")
            state["remediation"].append("Run 'certbot certificates' manually to verify renewal health")

    if renewal_confs and shutil.which("systemctl"):
        timer_enabled = False
        timer_active = False
        try:
            proc = _run(["systemctl", "is-enabled", "certbot.timer"], timeout=5)
            timer_enabled = proc.returncode == 0 and proc.stdout.strip() == "enabled"
        except Exception:
            pass
        try:
            proc = _run(["systemctl", "is-active", "certbot.timer"], timeout=5)
            timer_active = proc.returncode == 0 and proc.stdout.strip() == "active"
        except Exception:
            pass
        if not (timer_enabled and timer_active):
            if _has_certbot_renewal_cron():
                state["notes"].append(
                    "Let's Encrypt: certbot timer is not fully active, but a cron-based renewal job exists"
                )
            else:
                state["issues"].append(
                    f"Let's Encrypt: certbot renewal timer is not fully active ({'enabled' if timer_enabled else 'disabled'}, {'active' if timer_active else 'inactive'})"
                )
                state["remediation"].append("Enable/start certbot.timer or provide an equivalent renewal job")

    if live_names and renewal_confs and len(renewal_confs) < len(live_names):
        state["issues"].append(
            f"Let's Encrypt: {len(live_names)} live lineage(s) but only {len(renewal_confs)} renewal config(s)"
        )
        state["remediation"].append("Check for partial or stale /etc/letsencrypt state before the next renewal")

    if state["managed"]:
        if state["earliest_days"] is None:
            state["notes"].append(f"Let's Encrypt: {state['managed']} managed lineage(s) detected")
        else:
            state["notes"].append(
                f"Let's Encrypt: {state['managed']} managed lineage(s); earliest expiry in {state['earliest_days']}d"
            )

    return state


def _check_selinux_apparmor() -> tuple[list[str], list[str]]:
    """Return (issues, contextual notes) for SELinux/AppArmor state."""
    issues = []
    notes = []
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
                        notes.append("AppArmor: enabled, but no profiles are currently in enforce mode")
        except Exception:
            pass
    return issues, notes


def _check_reboot_required() -> dict:
    """Return explicit reboot-required state from distro tooling/markers."""
    state = {
        "required": False,
        "details": [],
        "packages": [],
        "source": None,
    }

    for path in _REBOOT_FLAG_PATHS:
        if not os.path.exists(path):
            continue
        state["required"] = True
        state["source"] = path
        state["details"].append(f"Reboot required marker present: {path}")
        break

    for path in _REBOOT_PKG_PATHS:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                pkgs = [line.strip() for line in f if line.strip()]
            if pkgs:
                state["packages"] = pkgs[:10]
                if len(pkgs) > 10:
                    state["details"].append(f"Reboot-required packages: {', '.join(pkgs[:10])} (+{len(pkgs) - 10} more)")
                else:
                    state["details"].append("Reboot-required packages: " + ", ".join(pkgs))
        except Exception:
            pass
        break

    if shutil.which("needs-restarting"):
        try:
            proc = _run(["needs-restarting", "-r"], timeout=20)
            if proc.returncode == 1:
                state["required"] = True
                state["source"] = state["source"] or "needs-restarting -r"
                state["details"].append("Reboot required according to needs-restarting -r")
            elif proc.returncode not in (0, 1):
                line = next((line.strip() for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()), None)
                if line:
                    state["details"].append(f"Reboot check note: {line}")
        except Exception:
            pass

    return state


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
        details.append(f"Certificates: none expiring within {_CERT_WARN_DAYS} days")

    le_state = _check_letsencrypt_state()
    details.extend(le_state["notes"])
    for issue in le_state["issues"]:
        details.append(issue)
        status = escalate(status, "WARN")
    remediation_parts.extend(le_state["remediation"])

    mac_issues, mac_notes = _check_selinux_apparmor()
    for issue in mac_issues:
        details.append(issue)
        status = escalate(status, "WARN")
    for note in mac_notes:
        details.append(note)
    if mac_issues:
        remediation_parts.append("Review SELinux/AppArmor policy mode against your host hardening baseline")

    reboot_state = _check_reboot_required()
    if reboot_state["required"]:
        status = escalate(status, "WARN")
        details.extend(reboot_state["details"])
        remediation_parts.append("Schedule and perform a controlled reboot once service impact is understood")
    elif reboot_state["details"]:
        details.extend(reboot_state["details"])
    else:
        details.append("Reboot status: no explicit reboot-required signal detected")

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
        if le_state["issues"]:
            parts.append("Let's Encrypt state to review")
        if mac_issues:
            parts.append("MAC policy to review")
        if reboot_state["required"]:
            parts.append("reboot pending")
        msg = "; ".join(parts) if parts else "security issues detected"

    remediation = "\n".join(dict.fromkeys(remediation_parts)) if status != "OK" and remediation_parts else None

    return Result(
        name="security",
        status=status,
        message=msg,
        details=details,
        remediation=remediation,
    )
