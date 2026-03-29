import os
import shutil
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_failed_systemd_services() -> list:
    """Return names of all failed systemd units."""
    failed = []
    try:
        proc = _run(["systemctl", "--failed", "--no-legend", "--plain"])
        for line in proc.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                failed.append(parts[0])
    except Exception:
        pass
    return failed


def _check_zombie_processes() -> tuple:
    """Return (count, details_list) of zombie processes."""
    count, details = 0, []
    try:
        proc = _run(["ps", "-eo", "pid,stat,comm"], timeout=10)
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and 'Z' in parts[1]:
                count += 1
                details.append(f"PID {parts[0]}: {parts[2]} (zombie)")
    except Exception:
        pass
    return count, details


def _check_pkg_manager_locks() -> list:
    """Detect stale or active package manager lock files."""
    issues = []
    lock_files = [
        ("/var/lib/dpkg/lock-frontend",    "apt"),
        ("/var/lib/dpkg/lock",             "apt"),
        ("/var/cache/apt/archives/lock",   "apt"),
        ("/var/lib/rpm/.rpm.lock",         "rpm"),
        ("/var/lib/pacman/db.lck",         "pacman"),
        ("/var/run/yum.pid",               "yum"),
        ("/var/run/dnf.pid",               "dnf"),
    ]
    for lock_path, manager in lock_files:
        if not os.path.exists(lock_path):
            continue
        # Check if the locking process is still alive
        alive = False
        try:
            import fcntl
            with open(lock_path, 'r') as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    # Lock acquired → previous holder is gone → stale lock
                    issues.append(f"Stale {manager} lock: {lock_path} (process dead)")
                except (IOError, OSError):
                    # Lock held → active package manager operation
                    issues.append(f"{manager} is currently running ({lock_path} locked)")
                    alive = True
        except Exception:
            issues.append(f"{manager} lock file present: {lock_path}")
    return issues


def _check_listening_ports() -> list:
    """Return list of (proto, addr, port) for all listening sockets."""
    sockets = []
    cmd = ["ss", "-tuln"] if shutil.which("ss") else ["netstat", "-tuln"]
    try:
        proc = _run(cmd, timeout=10)
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            proto       = parts[0]
            local_addr  = parts[4] if shutil.which("ss") else parts[3]
            # Handle [::]:port and 0.0.0.0:port
            if local_addr.startswith('['):
                bracket_end = local_addr.rfind(']')
                ip   = local_addr[1:bracket_end]
                port = local_addr[bracket_end + 2:]
            elif ':' in local_addr:
                ip, port = local_addr.rsplit(':', 1)
            else:
                continue
            sockets.append((proto, ip, port))
    except Exception:
        pass
    return sockets


def check() -> Result:
    """Systemd failed units, zombie processes, package manager locks."""
    details = []
    status  = "OK"
    remediation = None

    # Failed systemd services — CRIT
    failed = _check_failed_systemd_services()
    if failed:
        for svc in failed:
            details.append(f"Failed unit: {svc}")
        status = escalate(status, "CRIT")
        remediation = "systemctl status <unit> && journalctl -u <unit> -n 50"
    else:
        details.append("Systemd: no failed units")

    # Zombie processes — WARN
    zombie_count, zombie_details = _check_zombie_processes()
    if zombie_count:
        details.append(f"Zombie processes: {zombie_count}")
        details.extend(zombie_details[:10])
        status = escalate(status, "WARN")
        remediation = remediation or "Identify zombie parent: ps -eo pid,ppid,stat,comm | grep Z"
    else:
        details.append("Processes: no zombies")

    # Package manager locks — WARN/CRIT
    lock_issues = _check_pkg_manager_locks()
    for issue in lock_issues:
        details.append(issue)
        sev = "CRIT" if "stale" in issue.lower() else "WARN"
        status = escalate(status, sev)
        if "stale" in issue.lower():
            remediation = remediation or "Remove stale lock files then re-run package manager"

    # Listening ports summary (informational)
    sockets = _check_listening_ports()
    if sockets:
        details.append(f"Listening sockets: {len(sockets)} (use --verbose to list)")
    else:
        details.append("Listening sockets: unable to enumerate (ss/netstat not found)")

    if status == "OK":
        msg = (f"No failed units, no zombies"
               + (f", {len(sockets)} listening sockets" if sockets else ""))
    else:
        parts = []
        if failed:
            parts.append(f"{len(failed)} failed unit(s)")
        if zombie_count:
            parts.append(f"{zombie_count} zombie(s)")
        if lock_issues:
            parts.append(f"{len(lock_issues)} pkg lock(s)")
        msg = ", ".join(parts)

    return Result(
        name="services",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
