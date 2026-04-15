import os
import subprocess

from ..result import Result, escalate


def _service_exists(name: str) -> bool:
    try:
        proc = _run(["systemctl", "status", f"{name}.service"], timeout=5)
        combined = f"{proc.stdout}\n{proc.stderr}".lower()
        if "loaded:" in combined or "could not be found" not in combined:
            return proc.returncode in (0, 1, 2, 3) or "loaded:" in combined
    except Exception:
        pass
    return False


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _cron_service_running() -> bool:
    for svc in ("cron", "crond"):
        try:
            proc = _run(["systemctl", "is-active", svc], timeout=5)
            if proc.returncode == 0 and "active" in proc.stdout:
                return True
        except Exception:
            pass
    return False


def _check_crontabs() -> list:
    """Return list of crontab issue strings for human users."""
    issues = []
    nologin_shells = frozenset([
        "/sbin/nologin", "/bin/false", "/usr/sbin/nologin",
        "/bin/sync", "/usr/bin/sync",
    ])
    users = []
    try:
        with open("/etc/passwd") as f:
            for line in f:
                parts = line.rstrip('\n').split(":")
                if len(parts) < 7:
                    continue
                user, uid_str, shell = parts[0], parts[2], parts[6].strip()
                try:
                    uid = int(uid_str)
                except ValueError:
                    continue
                if 1000 <= uid < 65534 and shell not in nologin_shells:
                    users.append(user)
    except Exception:
        return issues

    for user in users:
        try:
            proc = _run(["crontab", "-l", "-u", user], timeout=5)
            if "no crontab for" in proc.stderr.lower():
                continue
            if proc.returncode != 0:
                issues.append(f"{user}: crontab unreadable")
                continue
            for line in proc.stdout.splitlines():
                l = line.strip()
                if not l or l.startswith("#"):
                    continue
                parts = l.split()
                if len(parts) < 6:
                    issues.append(f"{user}: malformed cron entry: '{l}'")
        except Exception:
            pass
    return issues


def _system_cron_entries() -> list[str]:
    """Return system-level cron entry paths that appear active."""
    entries = []
    cron_paths = [
        "/etc/crontab",
        "/etc/anacrontab",
    ]
    cron_dirs = [
        "/etc/cron.d",
        "/etc/cron.hourly",
        "/etc/cron.daily",
        "/etc/cron.weekly",
        "/etc/cron.monthly",
    ]

    for path in cron_paths:
        try:
            with open(path) as f:
                if any(line.strip() and not line.lstrip().startswith("#") for line in f):
                    entries.append(path)
        except OSError:
            pass

    for directory in cron_dirs:
        try:
            for name in sorted(os.listdir(directory)):
                full = os.path.join(directory, name)
                if name.startswith(".") or not os.path.isfile(full):
                    continue
                entries.append(full)
        except OSError:
            pass

    return entries


def _check_systemd_timers() -> list:
    """Return list of failed/inactive systemd timer names."""
    issues = []
    try:
        # Failed timers
        proc = _run(
            ["systemctl", "list-units", "--type=timer", "--state=failed",
             "--no-pager", "--no-legend"],
            timeout=10,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split()
                if parts and parts[0].endswith(".timer"):
                    issues.append(f"timer failed: {parts[0]}")
    except Exception:
        pass
    return issues


def _list_active_timers() -> int:
    """Return count of active systemd timers."""
    try:
        proc = _run(
            ["systemctl", "list-timers", "--no-pager", "--no-legend"],
            timeout=10,
        )
        if proc.returncode == 0:
            return sum(1 for l in proc.stdout.splitlines() if ".timer" in l)
    except Exception:
        pass
    return 0


def _list_crontab_users() -> list:
    """Return list of human users who have active crontabs."""
    users_with_crons = []
    nologin_shells = frozenset([
        "/sbin/nologin", "/bin/false", "/usr/sbin/nologin",
        "/bin/sync", "/usr/bin/sync",
    ])
    try:
        with open("/etc/passwd") as f:
            for line in f:
                parts = line.rstrip('\n').split(":")
                if len(parts) < 7:
                    continue
                user, uid_str, shell = parts[0], parts[2], parts[6].strip()
                try:
                    uid = int(uid_str)
                except ValueError:
                    continue
                if 1000 <= uid < 65534 and shell not in nologin_shells:
                    try:
                        proc = _run(["crontab", "-l", "-u", user], timeout=5)
                        if "no crontab for" not in proc.stderr.lower() and proc.returncode == 0:
                            if any(
                                l.strip() and not l.strip().startswith("#")
                                for l in proc.stdout.splitlines()
                            ):
                                users_with_crons.append(user)
                    except Exception:
                        pass
    except Exception:
        pass
    return users_with_crons


def check() -> Result:
    """Cron service, crontab validity, systemd timer failures."""
    details = []
    status  = "OK"
    remediation = None

    cron_running   = _cron_service_running()
    cron_issues    = _check_crontabs()
    timer_issues   = _check_systemd_timers()
    timer_count    = _list_active_timers()
    cron_users     = _list_crontab_users()
    system_cron    = _system_cron_entries()
    cron_installed = any(_service_exists(svc) for svc in ("cron", "crond"))
    cron_workload  = bool(cron_users or system_cron)

    # Cron service
    if cron_running:
        details.append("Cron service: running")
    elif cron_workload:
        details.append("Cron service: NOT running")
        status = escalate(status, "CRIT")
        remediation = "systemctl enable --now cron  (or crond on RHEL/CentOS)"
    elif cron_installed:
        details.append("Cron service: not running (no cron jobs detected)")
    else:
        details.append("Cron service: not installed")

    # Crontab issues
    if cron_issues:
        details.append(f"Crontab issues: {len(cron_issues)}")
        details.extend(cron_issues[:10])
        status = escalate(status, "WARN")
        remediation = remediation or "Review user crontabs: crontab -l -u <user>"
    else:
        if cron_users:
            details.append(f"User crontabs: {', '.join(cron_users)}")
        else:
            details.append("User crontabs: none configured")
        if system_cron:
            details.append(f"System cron entries: {len(system_cron)}")
            details.extend(system_cron[:10])
        else:
            details.append("System cron entries: none detected")

    # Systemd timers
    if timer_issues:
        details.append(f"Failed timers: {len(timer_issues)}")
        details.extend(timer_issues[:10])
        status = escalate(status, "CRIT")
        remediation = remediation or "systemctl status <timer> && journalctl -u <timer>"
    else:
        details.append(f"Systemd timers: {timer_count} active, none failed")

    # Message
    if status == "OK":
        parts = ["Cron running"]
        if cron_users:
            parts.append(f"{len(cron_users)} user crontab(s)")
        if timer_count:
            parts.append(f"{timer_count} systemd timer(s)")
        msg = ", ".join(parts)
    else:
        parts = []
        if not cron_running and cron_workload:
            parts.append("cron service down")
        if cron_issues:
            parts.append(f"{len(cron_issues)} crontab issue(s)")
        if timer_issues:
            parts.append(f"{len(timer_issues)} failed timer(s)")
        msg = ", ".join(parts) if parts else "scheduled task issues"

    return Result(
        name="scheduled",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
