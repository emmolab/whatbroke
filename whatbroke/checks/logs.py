import os
import subprocess
from collections import Counter

from ..result import Result, escalate

_JOURNAL_ERROR_WARN_THRESHOLD = 20
_KERNEL_WARN_THRESHOLD = 10
_LARGE_LOG_WARN_BYTES = 5 * 1024 * 1024 * 1024


def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _extract_systemd_unit(line: str) -> str | None:
    if "]: " in line:
        after = line.split("]: ", 1)[1]
        token = after.split()[0].rstrip(":")
        if ".service" in token or ".socket" in token or ".timer" in token:
            return token
    return None


def _check_journal_critical() -> tuple:
    """Return (critical_lines, error_lines) from the systemd journal."""
    critical, errors = [], []
    try:
        proc = _run(
            ["journalctl", "-p", "0..2", "--no-pager", "--output=short", "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            critical = [line for line in proc.stdout.strip().splitlines()[-100:] if line.strip()]
    except Exception:
        pass

    try:
        proc = _run(
            ["journalctl", "-p", "3", "--no-pager", "--output=short", "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            errors = [line for line in proc.stdout.strip().splitlines()[-200:] if line.strip()]
    except Exception:
        pass
    return critical, errors


def _check_kernel_messages() -> list:
    """Return kernel error/warning lines from dmesg / journal."""
    issues = []
    try:
        proc = _run(
            ["journalctl", "-k", "-p", "0..4", "--no-pager", "--output=short", "--since", "24 hours ago", "-q"],
            timeout=15,
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.strip().splitlines()[-100:] if line.strip()]
    except Exception:
        pass

    try:
        proc = _run(["dmesg", "--level", "err,warn,crit,alert,emerg"], timeout=10)
        if proc.returncode == 0:
            issues = [l for l in proc.stdout.strip().splitlines()[-100:] if l.strip()]
    except PermissionError:
        issues.append("kernel ring buffer: permission denied (run as root or adjust kernel.dmesg_restrict)")
    except Exception:
        pass
    return issues


def _check_oom_events() -> list:
    """Return lines describing OOM killer events in the last 24 h."""
    events = []
    try:
        proc = _run(
            ["journalctl", "-k", "--grep", "Out of memory:", "--since", "24 hours ago", "--no-pager", "-q", "--output=short"],
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [line.strip() for line in proc.stdout.strip().splitlines()[:20]]
    except Exception:
        pass

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
        ("/var/log/nginx/error.log", "nginx"),
        ("/var/log/apache2/error.log", "apache2"),
        ("/var/log/httpd/error_log", "httpd"),
        ("/var/log/mysql/error.log", "mysql"),
        ("/var/log/mariadb/mariadb.log", "mariadb"),
        ("/var/log/postgresql/postgresql.log", "postgresql"),
        ("/var/log/redis/redis-server.log", "redis"),
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
    """Return (path, size_bytes) for log files larger than threshold."""
    large = []
    try:
        proc = _run(["find", "/var/log", "-maxdepth", "3", "-name", "*.log", "-size", "+5G"], timeout=15)
        if proc.returncode == 0:
            for path in [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]:
                try:
                    large.append((path, os.path.getsize(path)))
                except OSError:
                    large.append((path, _LARGE_LOG_WARN_BYTES))
    except Exception:
        pass
    return large


def _format_size(num_bytes: int) -> str:
    gib = num_bytes / (1024 ** 3)
    return f"{gib:.1f} GiB"


def check() -> Result:
    """Journal errors, kernel messages, OOM events, app logs, large log files."""
    details = []
    status = "OK"
    remediation_parts = []

    critical, errors = _check_journal_critical()
    if critical:
        details.append(f"Journal critical/alert/emerg: {len(critical)} entries in last 24h")
        details.extend(critical[:5])
        status = escalate(status, "CRIT")
        remediation_parts.append("Inspect critical journal entries with: journalctl -p 0..2 --since '24 hours ago'")
    elif len(errors) >= _JOURNAL_ERROR_WARN_THRESHOLD:
        details.append(f"Journal err: {len(errors)} entries in last 24h")
        details.extend(errors[:3])
        units = Counter(unit for unit in (_extract_systemd_unit(line) for line in errors) if unit)
        if units:
            details.append("Top noisy units: " + ", ".join(f"{unit}: {count}" for unit, count in units.most_common(3)))
        status = escalate(status, "WARN")
        remediation_parts.append("Review recurring journal errors: journalctl -p 3 --since '24 hours ago'")
    elif errors:
        details.append(f"Journal err: {len(errors)} entries in last 24h (below alert threshold)")
    else:
        details.append("Journal: no critical/error entries in last 24h")

    oom_events = _check_oom_events()
    if oom_events:
        details.append(f"OOM killer: {len(oom_events)} event(s) in last 24h")
        details.extend(oom_events[:3])
        status = escalate(status, "CRIT")
        remediation_parts.append("Investigate memory pressure: free -h, ps aux --sort=-%mem")

    kernel_issues = _check_kernel_messages()
    if kernel_issues:
        severe_keywords = ("panic", "oops", "call trace", "filesystem corruption", "i/o error")
        severe_kernel = [line for line in kernel_issues if any(keyword in line.lower() for keyword in severe_keywords)]
        if severe_kernel:
            details.append(f"Kernel severe events: {len(severe_kernel)} in last 24h")
            details.extend(severe_kernel[:5])
            status = escalate(status, "CRIT")
            remediation_parts.append("Inspect kernel events with: journalctl -k -p 0..4 --since '24 hours ago'")
        elif len(kernel_issues) >= _KERNEL_WARN_THRESHOLD:
            details.append(f"Kernel warnings/errors: {len(kernel_issues)} in last 24h")
            details.extend(kernel_issues[:5])
            status = escalate(status, "WARN")
            remediation_parts.append("Review repeated kernel warnings with: journalctl -k -p 4 --since '24 hours ago'")
        else:
            details.append(f"Kernel warnings/errors: {len(kernel_issues)} in last 24h (below alert threshold)")
    else:
        details.append("Kernel: no warnings/errors detected")

    app_errors = _check_application_logs()
    if app_errors:
        details.append(f"Application log errors: {len(app_errors)} sample(s)")
        details.extend(app_errors[:10])
        status = escalate(status, "WARN")
        remediation_parts.append("Review the affected application logs under /var/log/")
    else:
        details.append("Application logs: no recent errors in common service logs")

    large_logs = _check_large_logs()
    if large_logs:
        details.append(f"Large log files (>5 GiB): {len(large_logs)}")
        for path, size in large_logs:
            details.append(f"  {path} ({_format_size(size)})")
        status = escalate(status, "WARN")
        remediation_parts.append("Check log rotation and retention settings")
    else:
        details.append("Log sizes: no files over 5 GiB in /var/log")

    if status == "OK":
        msg = "Logs look quiet enough for a normal server day"
    else:
        parts = []
        if critical:
            parts.append(f"{len(critical)} critical journal entries")
        elif len(errors) >= _JOURNAL_ERROR_WARN_THRESHOLD:
            parts.append(f"{len(errors)} journal errors")
        if oom_events:
            parts.append(f"{len(oom_events)} OOM event(s)")
        if kernel_issues:
            severe_keywords = ("panic", "oops", "call trace", "filesystem corruption", "i/o error")
            severe_kernel = [line for line in kernel_issues if any(keyword in line.lower() for keyword in severe_keywords)]
            if severe_kernel:
                parts.append(f"{len(severe_kernel)} severe kernel event(s)")
            elif len(kernel_issues) >= _KERNEL_WARN_THRESHOLD:
                parts.append(f"{len(kernel_issues)} kernel warnings")
        if app_errors:
            parts.append("application log errors")
        if large_logs:
            parts.append(f"{len(large_logs)} oversized log(s)")
        msg = ", ".join(parts) if parts else "log issues detected"

    remediation = "\n".join(dict.fromkeys(remediation_parts)) if status != "OK" and remediation_parts else None

    return Result(
        name="logs",
        status=status,
        message=msg,
        details=details,
        remediation=remediation,
    )
