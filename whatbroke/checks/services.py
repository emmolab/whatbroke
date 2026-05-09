import os
import pathlib
import shutil
import subprocess
from collections import Counter

from ..result import Result, escalate

_ZOMBIE_GRACE_SECONDS = 300
_ZOMBIE_WARN_COUNT = 3
_ZOMBIE_CRIT_COUNT = 10
_ZOMBIE_DETAIL_LIMIT = 8


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


def _parse_ps_zombies(ps_output: str) -> list[dict]:
    zombies = []
    for raw in ps_output.strip().splitlines()[1:]:
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, stat, etimes, comm = parts
        if "Z" not in stat:
            continue
        try:
            zombies.append(
                {
                    "pid": int(pid),
                    "ppid": int(ppid),
                    "stat": stat,
                    "etimes": int(etimes),
                    "comm": comm,
                }
            )
        except ValueError:
            continue
    return zombies


def _summarize_zombies(zombies: list[dict]) -> dict:
    stale = [z for z in zombies if z["etimes"] >= _ZOMBIE_GRACE_SECONDS]
    transient = [z for z in zombies if z["etimes"] < _ZOMBIE_GRACE_SECONDS]
    parent_counts = Counter(z["ppid"] for z in stale)
    commands = Counter(z["comm"] for z in stale)
    oldest = sorted(stale, key=lambda z: (-z["etimes"], z["pid"]))
    return {
        "all": zombies,
        "stale": stale,
        "transient": transient,
        "parent_counts": parent_counts,
        "commands": commands,
        "oldest": oldest,
    }


def _check_zombie_processes() -> dict:
    """Return parsed zombie information using richer ps fields."""
    try:
        proc = _run(["ps", "-eo", "pid=,ppid=,stat=,etimes=,comm="], timeout=10)
        if proc.returncode != 0:
            return {"all": [], "stale": [], "transient": [], "parent_counts": Counter(), "commands": Counter(), "oldest": []}
        return _summarize_zombies(_parse_ps_zombies(proc.stdout))
    except Exception:
        return {"all": [], "stale": [], "transient": [], "parent_counts": Counter(), "commands": Counter(), "oldest": []}


def _file_has_live_holder(path: str) -> bool:
    for tool in ("fuser", "lsof"):
        if not shutil.which(tool):
            continue
        try:
            cmd = [tool, path] if tool == "fuser" else [tool, path]
            proc = _run(cmd, timeout=5)
            if proc.returncode == 0 and (proc.stdout.strip() or proc.stderr.strip()):
                return True
        except Exception:
            pass
    return False


def _pid_is_running(pid: str) -> bool:
    return pid.isdigit() and os.path.exists(f"/proc/{pid}")


def _check_pkg_manager_locks() -> tuple[list[str], list[str], list[str]]:
    """Detect active package manager locks, while ignoring harmless leftover lock files."""
    issues: list[str] = []
    notes: list[str] = []
    remediation_notes: list[str] = []
    lock_files = [
        ("/var/lib/dpkg/lock-frontend", "apt", "file"),
        ("/var/lib/dpkg/lock", "apt", "file"),
        ("/var/cache/apt/archives/lock", "apt", "file"),
        ("/var/lib/rpm/.rpm.lock", "rpm", "file"),
        ("/var/lib/pacman/db.lck", "pacman", "file"),
        ("/var/run/yum.pid", "yum", "pid"),
        ("/var/run/dnf.pid", "dnf", "pid"),
    ]
    for lock_path, manager, lock_type in lock_files:
        if not os.path.exists(lock_path):
            continue
        try:
            if lock_type == "pid":
                pid = open(lock_path).read().strip()
                if _pid_is_running(pid):
                    issues.append(f"{manager} transaction in progress: pid {pid} ({lock_path})")
                else:
                    notes.append(f"Ignoring stale {manager} pid file: {lock_path}")
                continue

            if _file_has_live_holder(lock_path):
                issues.append(f"{manager} transaction in progress: {lock_path} is actively held")
                remediation_notes.append(f"Wait for the active {manager} transaction to finish before intervening")
            else:
                notes.append(f"Ignoring idle {manager} lock file: {lock_path}")
        except Exception:
            notes.append(f"Ignoring unreadable {manager} lock indicator: {lock_path}")
    return issues, notes, remediation_notes


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
            proto = parts[0]
            local_addr = parts[4] if shutil.which("ss") else parts[3]
            if local_addr.startswith("["):
                bracket_end = local_addr.rfind("]")
                ip = local_addr[1:bracket_end]
                port = local_addr[bracket_end + 2:]
            elif ":" in local_addr:
                ip, port = local_addr.rsplit(":", 1)
            else:
                continue
            sockets.append((proto, ip, port))
    except Exception:
        pass
    return sockets


def _read_os_release_tokens() -> set[str]:
    tokens: set[str] = set()
    path = pathlib.Path("/etc/os-release")
    try:
        for line in path.read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key not in {"ID", "ID_LIKE"}:
                continue
            tokens.update(part for part in value.strip().strip('"').lower().split() if part)
    except OSError:
        pass
    return tokens


def _detect_package_kind() -> str | None:
    """Best-effort host package family detection that avoids mixed-tool false positives."""
    tokens = _read_os_release_tokens()

    rpm_families = {"rhel", "fedora", "centos", "rocky", "alma", "suse", "opensuse"}
    deb_families = {"debian", "ubuntu"}

    if tokens & rpm_families and shutil.which("rpm"):
        return "rpm"
    if tokens & deb_families and shutil.which("dpkg"):
        return "deb"
    if any(shutil.which(tool) for tool in ("dnf", "yum", "zypper")):
        return "rpm"
    if shutil.which("apt-get"):
        return "deb"
    if shutil.which("rpm"):
        return "rpm"
    if shutil.which("dpkg"):
        return "deb"
    return None


def _check_package_health() -> tuple[list[str], list[str]]:
    """Detect conservative package-manager broken-state signals."""
    issues = []
    remediation = []

    if _detect_package_kind() == "deb":
        try:
            proc = _run(["dpkg", "--audit"], timeout=20)
            audit_output = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if audit_output:
                issues.append("dpkg audit reports packages needing repair/configuration")
                issues.extend(f"  {line}" for line in audit_output[:5])
                remediation.append("Repair package state with: sudo dpkg --configure -a && sudo apt -f install")
        except Exception:
            pass

    return issues, remediation


def check() -> Result:
    """Systemd failed units, zombie processes, package manager locks."""
    details = []
    status = "OK"
    remediation_parts = []

    failed = _check_failed_systemd_services()
    failed_details: list[str] = []
    if failed:
        failed_details.append(f"Systemd failed units: {len(failed)}")
        failed_details.extend(f"Failed unit: {svc}" for svc in failed[:10])
        status = escalate(status, "CRIT")
        remediation_parts.append("Inspect failed units with: systemctl status <unit> && journalctl -u <unit> -n 50")
    else:
        failed_details.append("Systemd: no failed units")

    zombie_info = _check_zombie_processes()
    stale_zombies = zombie_info["stale"]
    transient_zombies = zombie_info["transient"]
    total_zombies = len(zombie_info["all"])
    zombie_details: list[str] = []
    if stale_zombies:
        zombie_details.append(
            f"Zombie processes: {len(stale_zombies)} stale (>{_ZOMBIE_GRACE_SECONDS}s), {len(transient_zombies)} transient (<={_ZOMBIE_GRACE_SECONDS}s)"
        )
        for zombie in zombie_info["oldest"][:_ZOMBIE_DETAIL_LIMIT]:
            zombie_details.append(
                "Zombie PID {pid} ppid {ppid} stat {stat} age {etimes}s comm {comm}".format(**zombie)
            )
        if zombie_info["parent_counts"]:
            parent_summary = ", ".join(
                f"PPID {ppid}: {count}" for ppid, count in zombie_info["parent_counts"].most_common(3)
            )
            zombie_details.append(f"Zombie parents: {parent_summary}")
        if zombie_info["commands"]:
            command_summary = ", ".join(
                f"{comm}: {count}" for comm, count in zombie_info["commands"].most_common(3)
            )
            zombie_details.append(f"Zombie commands: {command_summary}")
        sev = "CRIT" if len(stale_zombies) >= _ZOMBIE_CRIT_COUNT else "WARN"
        status = escalate(status, sev)
        remediation_parts.append(
            "Identify the stuck parent process before restarting anything: ps -o pid,ppid,stat,etimes,comm -p <ppid>"
        )
        remediation_parts.append(
            "If the parent is unhealthy, restart the owning service cleanly instead of killing children individually"
        )
    elif transient_zombies:
        zombie_details.append(
            f"Zombie processes: {len(transient_zombies)} transient (<={_ZOMBIE_GRACE_SECONDS}s); not alerting yet"
        )
    else:
        zombie_details.append("Processes: no zombies")

    lock_issues, lock_notes, lock_remediation = _check_pkg_manager_locks()
    lock_details = []
    if lock_issues:
        lock_details.extend(lock_issues)
        status = escalate(status, "WARN")
    elif lock_notes:
        lock_details.append("Package manager locks: none active")
    remediation_parts.extend(lock_remediation)

    package_issues, package_remediation = _check_package_health()
    package_details = []
    if package_issues:
        package_details.extend(package_issues)
        status = escalate(status, "BROKE")
        remediation_parts.extend(package_remediation)

    sockets = _check_listening_ports()
    socket_details = [f"Listening sockets: {len(sockets)}"] if sockets else ["Listening sockets: unable to enumerate (ss/netstat not found)"]

    if status == "OK":
        details.extend(failed_details)
        details.extend(zombie_details)
        details.extend(lock_details)
        details.extend(package_details)
        details.extend(socket_details)
        msg = f"No failed units, no stale zombies, {len(sockets)} listening sockets" if sockets else "No failed units or stale zombies"
    else:
        details.extend(failed_details)
        if stale_zombies:
            details.extend(zombie_details)
        details.extend([issue for issue in lock_details if "transaction in progress" in issue])
        if package_issues:
            details.extend(package_details[:6])
        parts = []
        if failed:
            parts.append(f"{len(failed)} failed unit(s)")
        if stale_zombies:
            parts.append(f"{len(stale_zombies)} stale zombie(s)")
        if lock_issues:
            parts.append(f"{len(lock_issues)} active pkg transaction(s)")
        if package_issues:
            parts.append("package state needs repair")
        msg = ", ".join(parts)

    remediation = "\n".join(dict.fromkeys(remediation_parts)) if status != "OK" and remediation_parts else None

    return Result(
        name="services",
        status=status,
        message=msg,
        details=details,
        remediation=remediation,
    )
