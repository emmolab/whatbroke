import subprocess

from ..result import Result, escalate

_WARN_THRESHOLD = 50
_CRIT_THRESHOLD = 500

_MTA_NAMES = ("postfix", "exim4", "exim", "sendmail", "opensmtpd")


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "", ""


def _service_active(name: str) -> bool:
    rc, _, _ = _run(["systemctl", "is-active", "--quiet", name])
    return rc == 0


def _detect_mta() -> str | None:
    """Return the name of the first installed MTA, or None."""
    for name in _MTA_NAMES:
        rc, _, _ = _run(["systemctl", "cat", name + ".service"])
        if rc == 0:
            return name
        rc2, _, _ = _run(["which", name])
        if rc2 == 0:
            return name
    return None


# ── Per-MTA queue-size helpers ───────────────────────────────────────────────

def _postfix_queue_size() -> int | None:
    """Count messages in postfix queue (via mailq)."""
    rc, out, _ = _run(["mailq"])
    if rc == -1:
        return None
    if "Mail queue is empty" in out:
        return 0
    # Each queued message has a line starting with a hex queue ID (no leading space)
    count = sum(
        1 for line in out.splitlines()
        if line and not line.startswith((" ", "\t", "-", "M", "p", "/"))
        and line[:1].isalnum()
    )
    return max(count, 0)


def _exim_queue_size() -> int | None:
    rc, out, _ = _run(["exim", "-bpc"])
    if rc == -1:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def _opensmtpd_queue_size() -> int | None:
    rc, out, _ = _run(["smtpctl", "show", "stats"])
    if rc == -1:
        return None
    total = 0
    for line in out.splitlines():
        if "scheduler.envelope" in line and "incoming" not in line:
            try:
                total += int(line.split("=")[-1].strip())
            except ValueError:
                pass
    return total or None


def _mailq_count() -> int | None:
    """Generic mailq parser — works for postfix and sendmail."""
    rc, out, _ = _run(["mailq"])
    if rc == -1:
        return None
    if "Mail queue is empty" in out:
        return 0
    # sendmail footer: "Total requests: N"
    for line in reversed(out.splitlines()):
        if "request" in line.lower():
            try:
                return int(line.split()[-1])
            except (ValueError, IndexError):
                pass
    # postfix: count queue-ID lines
    return sum(
        1 for line in out.splitlines()
        if line and line[:1].isalnum() and not line.startswith(("Mail", "p", "M"))
    )


def _queue_size(mta: str) -> int | None:
    if mta in ("exim4", "exim"):
        return _exim_queue_size()
    if mta == "opensmtpd":
        return _opensmtpd_queue_size()
    # postfix and sendmail both expose mailq
    return _mailq_count()


# ── Main check ───────────────────────────────────────────────────────────────

def check() -> Result:
    """Mail transfer agent health and queue depth."""
    details = []
    status = "OK"
    issues = []

    mta = _detect_mta()
    if mta is None:
        return Result(
            name="mail",
            status="OK",
            message="No MTA detected — mail checks skipped",
        )

    details.append(f"MTA detected: {mta}")

    # Service running?
    running = _service_active(mta)
    # opensmtpd uses unit name "smtpd" on some distros
    if not running and mta == "opensmtpd":
        running = _service_active("smtpd")

    if not running:
        issues.append(f"{mta} service is not running")
        status = escalate(status, "CRIT")
    else:
        details.append(f"{mta} service: running")

    # Queue depth
    queue = _queue_size(mta)
    if queue is None:
        details.append("Queue size: unknown (mailq not accessible)")
    elif queue >= _CRIT_THRESHOLD:
        issues.append(f"Mail queue critically large: {queue} messages (>= {_CRIT_THRESHOLD})")
        status = escalate(status, "CRIT")
    elif queue >= _WARN_THRESHOLD:
        issues.append(f"Mail queue growing: {queue} messages (>= {_WARN_THRESHOLD})")
        status = escalate(status, "WARN")
    else:
        details.append(f"Queue depth: {queue} messages  OK")

    all_details = issues + details

    if status == "OK":
        q_str = f", queue: {queue}" if queue is not None else ""
        msg = f"{mta} healthy{q_str}"
    else:
        msg = "; ".join(issues)

    return Result(
        name="mail",
        status=status,
        message=msg,
        details=all_details,
        remediation=(
            f"Check '{mta}' logs: journalctl -u {mta} -n 50\n"
            "  Inspect queue: mailq\n"
            "  Flush queue:   postfix flush  (or: sendmail -q)"
        ) if status != "OK" else None,
    )
