import os
import pwd
import re
import subprocess

from ..result import Result, escalate


_CRON_MACROS = {
    "@reboot",
    "@yearly",
    "@annually",
    "@monthly",
    "@weekly",
    "@daily",
    "@midnight",
    "@hourly",
}

_ANACRON_PERIOD_RE = re.compile(r"^(?:\d+|@[A-Za-z][A-Za-z0-9_-]*)$")
_ANACRON_DELAY_RE = re.compile(r"^\d+$")

_CRON_BACKUP_SUFFIXES = (
    "~",
    ".bak",
    ".dpkg-dist",
    ".dpkg-old",
    ".dpkg-new",
    ".disabled",
    ".orig",
    ".rpmnew",
    ".rpmsave",
    ".sample",
    ".swp",
)

_RUN_PARTS_DIRS = {
    "/etc/cron.hourly",
    "/etc/cron.daily",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
}


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


def _crontab_list_command(user: str) -> list[str] | None:
    """Return the safest crontab -l command for this execution context.

    Non-root runs can only inspect their own crontab reliably, so skip other
    users instead of emitting false "unreadable" alerts.
    """
    try:
        current_user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        current_user = None

    if os.geteuid() == 0:
        return ["crontab", "-l", "-u", user]
    if current_user and user == current_user:
        return ["crontab", "-l"]
    return None


def _crontab_permission_denied(proc) -> bool:
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    markers = (
        "must be privileged to use -u",
        "you are not allowed to use this program",
        "not allowed to use this program",
        "permission denied",
    )
    return any(marker in combined for marker in markers)


def _line_has_cron_workload(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and not stripped.startswith("#") and not _looks_like_env_assignment(stripped))


def _user_cron_issue_from_line(user: str, line: str) -> str | None:
    stripped = line.strip()
    if not _line_has_cron_workload(stripped):
        return None

    parts = stripped.split()
    if not parts:
        return None

    if parts[0].lower() in _CRON_MACROS:
        if len(parts) < 2:
            return f"{user}: malformed cron macro entry: '{stripped}'"
        return None

    if len(parts) < 6:
        return f"{user}: malformed cron entry: '{stripped}'"
    return None



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
            cmd = _crontab_list_command(user)
            if not cmd:
                continue
            proc = _run(cmd, timeout=5)
            if "no crontab for" in proc.stderr.lower():
                continue
            if _crontab_permission_denied(proc):
                continue
            if proc.returncode != 0:
                issues.append(f"{user}: crontab unreadable")
                continue
            for line in proc.stdout.splitlines():
                issue = _user_cron_issue_from_line(user, line)
                if issue:
                    issues.append(issue)
        except Exception:
            pass
    return issues


_CRON_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=.*$")


def _looks_like_env_assignment(line: str) -> bool:
    return bool(_CRON_ENV_ASSIGNMENT_RE.match(line.strip()))



def _cron_entry_disabled_name(name: str) -> bool:
    return name.startswith(".") or name.endswith(_CRON_BACKUP_SUFFIXES)



def _run_parts_entry_active(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)



def _system_cron_entry_active(path: str) -> bool:
    name = os.path.basename(path)
    if _cron_entry_disabled_name(name):
        return False
    parent = os.path.dirname(path)
    if parent in _RUN_PARTS_DIRS:
        return _run_parts_entry_active(path)
    return os.path.isfile(path)



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
                if any(_line_has_cron_workload(line) for line in f):
                    entries.append(path)
        except OSError:
            pass

    for directory in cron_dirs:
        try:
            for name in sorted(os.listdir(directory)):
                full = os.path.join(directory, name)
                if not _system_cron_entry_active(full):
                    continue
                entries.append(full)
        except OSError:
            pass

    return entries



def _system_cron_issue_from_line(path: str, line_no: int, line: str) -> str | None:
    stripped = line.strip()
    if not _line_has_cron_workload(stripped):
        return None

    parts = stripped.split()
    if not parts:
        return None

    if parts[0].lower() in _CRON_MACROS:
        if len(parts) < 3:
            return f"{path}:{line_no}: malformed system cron macro entry: '{stripped}'"
        return None

    if len(parts) < 7:
        return f"{path}:{line_no}: malformed system cron entry: '{stripped}'"
    return None



def _anacron_issue_from_line(path: str, line_no: int, line: str) -> str | None:
    stripped = line.strip()
    if not _line_has_cron_workload(stripped):
        return None

    parts = stripped.split()
    if len(parts) < 4:
        return f"{path}:{line_no}: malformed anacrontab entry: '{stripped}'"

    period, delay = parts[0], parts[1]
    if not _ANACRON_PERIOD_RE.match(period) or not _ANACRON_DELAY_RE.match(delay):
        return f"{path}:{line_no}: malformed anacrontab entry: '{stripped}'"
    return None



def _check_system_cron_syntax() -> list[str]:
    issues = []
    cron_files = [("/etc/crontab", _system_cron_issue_from_line), ("/etc/anacrontab", _anacron_issue_from_line)]
    cron_dir = "/etc/cron.d"

    if os.path.isdir(cron_dir):
        for name in sorted(os.listdir(cron_dir)):
            full = os.path.join(cron_dir, name)
            if _system_cron_entry_active(full):
                cron_files.append((full, _system_cron_issue_from_line))

    for path, issue_from_line in cron_files:
        try:
            with open(path) as handle:
                for line_no, line in enumerate(handle, start=1):
                    issue = issue_from_line(path, line_no, line)
                    if issue:
                        issues.append(issue)
        except OSError:
            continue

    return issues


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
                        cmd = _crontab_list_command(user)
                        if not cmd:
                            continue
                        proc = _run(cmd, timeout=5)
                        if "no crontab for" not in proc.stderr.lower() and proc.returncode == 0:
                            if any(_line_has_cron_workload(line) for line in proc.stdout.splitlines()):
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
    system_cron_issues = _check_system_cron_syntax()
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
    combined_cron_issues = cron_issues + system_cron_issues
    if combined_cron_issues:
        details.append(f"Crontab issues: {len(combined_cron_issues)}")
        details.extend(combined_cron_issues[:10])
        status = escalate(status, "WARN")
        remediation = remediation or "Review user crontabs and system cron files: crontab -l -u <user>, /etc/crontab, /etc/anacrontab, /etc/cron.d/*"
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
        if cron_running:
            cron_summary = "Cron running"
        elif cron_workload:
            cron_summary = "Cron configured"
        elif cron_installed:
            cron_summary = "Cron installed but idle"
        else:
            cron_summary = "Cron not installed"

        parts = [cron_summary]
        if cron_users:
            parts.append(f"{len(cron_users)} user crontab(s)")
        if timer_count:
            parts.append(f"{timer_count} systemd timer(s)")
        msg = ", ".join(parts)
    else:
        parts = []
        if not cron_running and cron_workload:
            parts.append("cron service down")
        if combined_cron_issues:
            parts.append(f"{len(combined_cron_issues)} crontab issue(s)")
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
