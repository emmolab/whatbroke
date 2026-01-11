import os
import subprocess

from whatbroke.result import Result


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------
# Cron
# ---------------------------

def _cron_service_running():
    for svc in ("cron", "crond"):
        r = _run(["systemctl", "is-active", svc])
        if r.returncode == 0 and "active" in r.stdout:
            return True
    return False


def _check_crontabs():
    issues = []

    if not os.path.exists("/etc/passwd"):
        return issues

    with open("/etc/passwd") as f:
        users = []
        for l in f:
            parts = l.split(":")
            if len(parts) >= 3:
                user = parts[0]
                uid = parts[2]
                # Skip system users (UID < 1000 or UID >= 65534) and users with no shell or invalid shells
                try:
                    uid_int = int(uid)
                    if uid_int >= 1000 and uid_int < 65534 and len(parts) > 6:
                        shell = parts[6]
                        # Skip users with nologin, false, sync, or system shells
                        if shell not in ["/sbin/nologin", "/bin/false", "/usr/sbin/nologin", "/bin/sync", "/usr/bin/sync"]:
                            users.append(user)
                except ValueError:
                    continue

    for user in users:
        r = _run(["crontab", "-l", "-u", user])

        # Explicitly skip users with no crontab
        if "no crontab for" in r.stderr.lower():
            continue

        if r.returncode != 0:
            issues.append(f"{user}: crontab unreadable")
            continue

        for line in r.stdout.splitlines():
            l = line.strip()
            if not l or l.startswith("#"):
                continue

            # Basic structural validation
            parts = l.split()
            if len(parts) < 6:
                issues.append(f"{user}: malformed entry: '{l}'")
                continue

            # Validate time fields (should be 5 time fields)
            time_fields = parts[:5]
            for i, field in enumerate(time_fields):
                if field == "*":
                    continue
                # Check for valid cron patterns
                if i < 4:  # minute, hour, day of month, month
                    try:
                        if "/" in field:
                            base, step = field.split("/")
                            if base != "*" and not base.isdigit():
                                issues.append(f"{user}: invalid time field '{field}' in '{l}'")
                                break
                        elif "," in field:
                            for val in field.split(","):
                                if val != "*" and not val.isdigit():
                                    issues.append(f"{user}: invalid time field '{field}' in '{l}'")
                                    break
                        elif "-" in field:
                            start, end = field.split("-")
                            if not start.isdigit() or not end.isdigit():
                                issues.append(f"{user}: invalid time field '{field}' in '{l}'")
                                break
                        elif field != "*" and not field.isdigit():
                            issues.append(f"{user}: invalid time field '{field}' in '{l}'")
                            break
                    except:
                        issues.append(f"{user}: invalid time field '{field}' in '{l}'")
                        break

    return issues


# ---------------------------
# systemd timers
# ---------------------------

def _check_systemd_timers():
    issues = []

    # Failed timers (authoritative)
    r = _run(["systemctl", "list-timers", "--failed", "--no-pager"])
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if ".timer" in line:
                issues.append(f"timer failed: {line.split()[0]}")

    # Inactive timers (non-system)
    r = _run(["systemctl", "list-timers", "--all", "--no-pager"])
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if ".timer" not in line:
                continue
            if "inactive" in line.lower() and not line.startswith("systemd-"):
                issues.append(f"timer inactive: {line.split()[0]}")

    return issues


# ---------------------------
# Entry
# ---------------------------

def check():
    details = []
    status = "OK"
    remediation = None

    cron_running = _cron_service_running()
    cron_issues = _check_crontabs()

    timer_issues = _check_systemd_timers()

    if not cron_running:
        status = "CRIT"
        details.append("cron service not running")
        remediation = "enable cron service"
    elif cron_issues:
        status = "WARN"
        details.extend(cron_issues)
        remediation = "review user crontabs"

    if timer_issues:
        if status != "CRIT":
            status = "CRIT"
        details.extend(timer_issues)
        if not remediation:
            remediation = "check systemd timers"

    if status == "OK":
        # Provide more detailed info for OK status
        details = []
        
        # Add cron service status
        if cron_running:
            details.append("Cron service: Active and running")
        else:
            details.append("Cron service: Not running")
        
        # Count valid users that could have crontabs
        with open("/etc/passwd") as f:
            users = []
            for l in f:
                parts = l.split(":")
                if len(parts) >= 3:
                    user = parts[0]
                    uid = parts[2]
                    try:
                        uid_int = int(uid)
                        if uid_int >= 1000 and uid_int < 65534 and len(parts) > 6:
                            shell = parts[6]
                            if shell not in ["/sbin/nologin", "/bin/false", "/usr/sbin/nologin", "/bin/sync", "/usr/bin/sync"]:
                                users.append(user)
                    except ValueError:
                        continue
        
        # Check if any users actually have crontabs
        crontab_users = []
        for user in users:
            r = _run(["crontab", "-l", "-u", user])
            if "no crontab for" not in r.stderr.lower() and r.returncode == 0:
                crontab_users.append(user)
        
        # Add user crontab information
        if crontab_users:
            details.append(f"User crontabs found: {', '.join(crontab_users)}")
        else:
            details.append("User crontabs: No user crontabs found")
        
        # Check systemd timers
        r = _run(["systemctl", "list-timers", "--no-pager"])
        timer_count = 0
        if r.returncode == 0:
            timer_count = len([l for l in r.stdout.splitlines() if ".timer" in l and not l.startswith("NEXT")])
        
        # Add timer information
        if timer_count > 0:
            details.append(f"Systemd timers: {timer_count} active timers found")
        else:
            details.append("Systemd timers: No active timers found")
        
        # Build status message
        status_msg_parts = []
        if cron_running:
            status_msg_parts.append("Cron service running")
        else:
            status_msg_parts.append("Cron service not running")
        
        if crontab_users:
            status_msg_parts.append(f"{len(crontab_users)} user crontabs")
        else:
            status_msg_parts.append("no user crontabs")
        
        if timer_count > 0:
            status_msg_parts.append(f"{timer_count} systemd timers")
        else:
            status_msg_parts.append("no systemd timers")
        
        return Result(
            name="scheduled", 
            status="OK", 
            message=", ".join(status_msg_parts),
            details=details
        )

    return Result(
        name="scheduled",
        status=status,
        message="issues",
        details=details[:10],
        remediation=remediation,
    )
