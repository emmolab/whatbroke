import subprocess

from ..result import Result, escalate

# Shell paths that indicate an interactive login account
_LOGIN_SHELLS = frozenset([
    "/bin/sh", "/bin/bash", "/bin/zsh", "/bin/fish",
    "/usr/bin/sh", "/usr/bin/bash", "/usr/bin/zsh", "/usr/bin/fish",
    "/usr/bin/ksh", "/bin/ksh", "/usr/bin/tcsh", "/bin/tcsh",
    "/usr/bin/dash", "/bin/dash",
])

# Well-known system accounts that legitimately have UID 0 on some distros
_EXPECTED_UID0 = frozenset(["root"])


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "", ""


def _parse_passwd():
    """Parse /etc/passwd into list of dicts."""
    entries = []
    try:
        with open("/etc/passwd") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) < 7:
                    continue
                entries.append({
                    "name":  parts[0],
                    "uid":   int(parts[2]) if parts[2].isdigit() else -1,
                    "gid":   int(parts[3]) if parts[3].isdigit() else -1,
                    "home":  parts[5],
                    "shell": parts[6],
                })
    except OSError:
        pass
    return entries


def _parse_shadow_empty_passwords():
    """Return list of usernames with empty passwords (requires read access to /etc/shadow)."""
    empty = []
    try:
        with open("/etc/shadow") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) < 2:
                    continue
                name, pw = parts[0], parts[1]
                # Empty string = no password; '!' or '*' = locked account
                if pw == "":
                    empty.append(name)
    except (OSError, PermissionError):
        pass
    return empty


def _check_sudoers():
    """Return list of issue strings from sudoers (NOPASSWD, ALL, wildcards)."""
    issues = []
    files = ["/etc/sudoers"]
    try:
        import glob as _glob
        files += sorted(_glob.glob("/etc/sudoers.d/*"))
    except Exception:
        pass

    for path in files:
        try:
            with open(path) as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if "NOPASSWD" in stripped and "ALL" in stripped:
                        # Suppress very common/expected patterns (e.g. %wheel NOPASSWD: ALL)
                        issues.append(
                            f"{path}:{lineno}: NOPASSWD:ALL grant — {stripped[:80]}"
                        )
        except (OSError, PermissionError):
            pass

    return issues


def check() -> Result:
    """User account hygiene: UID-0 accounts, empty passwords, dangerous sudoers."""
    details = []
    issues = []
    status = "OK"

    entries = _parse_passwd()
    if not entries:
        return Result(
            name="users",
            status="OK",
            message="/etc/passwd unreadable — skipping user checks",
        )

    # ── Extra UID-0 accounts ─────────────────────────────────────────────────
    uid0 = [e["name"] for e in entries if e["uid"] == 0 and e["name"] not in _EXPECTED_UID0]
    for name in uid0:
        issues.append(f"UID 0 account (non-root): {name}")
        status = escalate(status, "CRIT")

    # ── Login-shell accounts with very low UIDs (likely system accts with shell) ──
    suspicious_shell = [
        e for e in entries
        if 0 < e["uid"] < 100
        and e["shell"] in _LOGIN_SHELLS
        and e["name"] not in ("sync", "halt", "shutdown")
    ]
    for e in suspicious_shell:
        issues.append(
            f"System account with login shell: {e['name']} (uid={e['uid']}, shell={e['shell']})"
        )
        status = escalate(status, "WARN")

    # ── Empty passwords ──────────────────────────────────────────────────────
    empty_pw = _parse_shadow_empty_passwords()
    for name in empty_pw:
        issues.append(f"Empty password: {name}")
        status = escalate(status, "CRIT")

    # ── Sudoers ──────────────────────────────────────────────────────────────
    sudoers_issues = _check_sudoers()
    for s in sudoers_issues:
        issues.append(s)
        status = escalate(status, "WARN")

    # ── Informational summary ────────────────────────────────────────────────
    login_users = [e for e in entries if e["shell"] in _LOGIN_SHELLS and e["uid"] >= 1000]
    if login_users:
        details.append(
            "Login accounts (uid>=1000): " + ", ".join(e["name"] for e in login_users)
        )

    system_count = sum(1 for e in entries if e["uid"] < 1000)
    details.append(f"System accounts: {system_count}")

    all_details = issues + details

    if status == "OK":
        msg = f"User accounts look clean ({len(entries)} total, {len(login_users)} login)"
    else:
        msg = f"{len(issues)} user account issue(s)"

    return Result(
        name="users",
        status=status,
        message=msg,
        details=all_details,
        remediation=(
            "Review flagged accounts:\n"
            "  Extra UID-0: passwd -l <user>  or  usermod -s /sbin/nologin <user>\n"
            "  Empty password: passwd <user>\n"
            "  Sudoers: visudo"
        ) if status != "OK" else None,
    )
