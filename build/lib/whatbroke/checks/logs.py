import os
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_journal_critical() -> tuple:
    """Return (critical_lines, error_lines) from the systemd journal."""
    critical, errors = [], []
    try:
        # Priority 0-2: emerg, alert, crit
        proc = _run(
            ["journalctl", "-p", "0..2", "--no-pager", "--output=short",
             "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[-100:]:
                if line.strip():
                    critical.append(line)
    except Exception:
        pass

    try:
        # Priority 3: err — last 24 h
        proc = _run(
            ["journalctl", "-p", "3", "--no-pager", "--output=short",
             "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[-100:]:
                if line.strip():
                    errors.append(line)
    except Exception:
        pass
    return critical, errors


def _check_kernel_messages() -> list:
    """Return kernel error/warning lines from dmesg / journal."""
    issues = []
    try:
        proc = _run(
            ["journalctl", "-k", "-p", "0..4", "--no-pager", "--output=short",
             "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[-50:]:
                if line.strip():
                    issues.append(line)
            return issues
    except Exception:
        pass

    # Fallback to dmesg (may require root on hardened systems)
    try:
        proc = _run(["dmesg", "--level", "err,warn,crit,alert,emerg"], timeout=10)
        if proc.returncode == 0:
            issues = [l for l in proc.stdout.strip().splitlines()[-50:] if l.strip()]
    except PermissionError:
        issues.append("kernel ring buffer: permission denied "
                      "(run as root or adjust kernel.dmesg_restrict)")
    except Exception:
        pass
    return issues


def _check_oom_events() -> list:
    """Return lines describing OOM killer events in the last 24 h."""
    events = []
    try:
        proc = _run(
            ["journalctl", "-k", "--grep", "Out of memory:",
             "--since", "24 hours ago", "--no-pager", "-q", "--output=short"],
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().splitlines()[:20]:
                events.append(line.strip())
            return events
    except Exception:
        pass

    # dmesg fallback
    try:
        proc = _run(["dmesg"], timeout=10)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if "out of memory" in line.lower() or "oom" in line.lower():
                    events.append(line.strip())
    except Exception:
        pass
    return events


def _check_application_logs() -> list:
    """Scan well-known application log files for recent errors."""
    app_errors = []
    log_files = [
        ("/var/log/nginx/error.log",           "nginx"),
        ("/var/log/apache2/error.log",          "apache2"),
        ("/var/log/httpd/error_log",            "httpd"),
        ("/var/log/mysql/error.log",            "mysql"),
        ("/var/log/mariadb/mariadb.log",        "mariadb"),
        ("/var/log/postgresql/postgresql.log",  "postgresql"),
        ("/var/log/redis/redis-server.log",     "redis"),
    ]
    for log_path, app in log_files:
        if not os.path.exists(log_path):
            continue
        try:
            proc = _run(["tail", "-n", "20", log_path], timeout=10)
            if proc.returncode != 0:
                continue
            count = 0
            for line in proc.stdout.splitlines():
                if any(kw in line.lower() for kw in ("error", "fatal", "critical", "panic")):
                    count += 1
                    if count <= 3:
                        app_errors.append(f"{app}: {line.strip()[:200]}")
            if count > 3:
                app_errors.append(f"{app}: ...and {count - 3} more error lines in last 20")
        except Exception:
            pass
    return app_errors


def _check_large_logs() -> list:
    """Return paths of log files larger than 1 GB."""
    large = []
    try:
        proc = _run(
            ["find", "/var/log", "-maxdepth", "3", "-name", "*.log",
             "-size", "+1G"],
            timeout=15,
        )
        if proc.returncode == 0:
            large = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
    except Exception:
        pass
    return large


def check() -> Result:
    """Journal errors, kernel messages, OOM events, app logs, large log files."""
    details = []
    status  = "OK"
    remediation = None

    # Journal critical/error entries
    critical, errors = _check_journal_critical()
    if critical:
        details.append(f"Journal CRITICAL/ALERT/EMERG: {len(critical)} entries (last 24 h)")
        details.extend(critical[:5])
        status = escalate(status, "CRIT")
        remediation = "journalctl -p 0..2 -xb --no-pager"
    elif errors:
        details.append(f"Journal ERR: {len(errors)} entries (last 24 h)")
        details.extend(errors[:3])
        status = escalate(status, "WARN")
        remediation = "journalctl -p 3 --since '24 hours ago' --no-pager"
    else:
        details.append("Journal: no critical/error entries in last 24 h")

    # OOM events — evaluated separately from general kernel errors
    oom_events = _check_oom_events()
    if oom_events:
        details.append(f"OOM killer: {len(oom_events)} event(s) in last 24 h — memory exhaustion")
        details.extend(oom_events[:3])
        status = escalate(status, "CRIT")
        remediation = remediation or "Investigate memory: free -h, ps aux --sort=-%mem"

    # Kernel messages
    kernel_issues = _check_kernel_messages()
    if kernel_issues:
        panic = any("panic" in l.lower() or "oops" in l.lower() for l in kernel_issues)
        details.append(f"Kernel: {len(kernel_issues)} issue(s) in dmesg/journal")
        details.extend(kernel_issues[:5])
        sev = "CRIT" if panic else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "dmesg --level err,warn | tail -50"
    else:
        details.append("Kernel: no errors/warnings")

    # Application logs
    app_errors = _check_application_logs()
    if app_errors:
        details.append(f"Application logs: {len(app_errors)} error line(s)")
        details.extend(app_errors[:10])
        status = escalate(status, "WARN")
        remediation = remediation or "Review application logs in /var/log/"
    else:
        details.append("Application logs: no recent errors")

    # Large log files
    large_logs = _check_large_logs()
    if large_logs:
        details.append(f"Large log files (>1 GB): {len(large_logs)}")
        for path in large_logs:
            details.append(f"  {path}")
        status = escalate(status, "WARN")
        remediation = remediation or "Rotate logs: logrotate -f /etc/logrotate.conf"
    else:
        details.append("Log sizes: no files >1 GB")

    if status == "OK":
        msg = "All log checks clean — no issues in last 24 h"
    else:
        parts = []
        if critical:
            parts.append(f"{len(critical)} critical journal entries")
        elif errors:
            parts.append(f"{len(errors)} error journal entries")
        if oom_events:
            parts.append(f"{len(oom_events)} OOM event(s)")
        if kernel_issues:
            parts.append(f"{len(kernel_issues)} kernel issues")
        if app_errors:
            parts.append("app log errors")
        msg = ", ".join(parts) if parts else "log issues detected"

    return Result(
        name="logs",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
