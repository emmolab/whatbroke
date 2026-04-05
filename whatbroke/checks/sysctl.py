from ..result import Result, escalate

# Each entry: (sysctl_key, expected, severity_if_wrong, description)
# expected=None means "just report the value" (informational)
_SECURITY_PARAMS = [
    (
        "kernel.randomize_va_space",
        "2", "WARN",
        "ASLR not fully enabled (should be 2)",
    ),
    (
        "net.ipv4.tcp_syncookies",
        "1", "WARN",
        "TCP SYN cookie protection disabled — host vulnerable to SYN flood",
    ),
    (
        "net.ipv4.conf.all.accept_redirects",
        "0", "WARN",
        "ICMP redirect acceptance enabled — routing can be manipulated",
    ),
    (
        "net.ipv4.conf.default.accept_redirects",
        "0", "WARN",
        "ICMP redirect acceptance enabled on new interfaces",
    ),
]

_CONTEXT_PARAMS = [
    (
        "fs.suid_dumpable",
        None, None,
        "informational: 0 is stricter; 2 is also common on systemd-coredump hosts",
    ),
    (
        "kernel.dmesg_restrict",
        None, None,
        "informational: many server baselines prefer 1, but 0 is still seen on general-purpose hosts",
    ),
    (
        "kernel.kptr_restrict",
        None, None,
        "informational: hardened hosts often use >= 1",
    ),
    (
        "net.ipv6.conf.all.accept_redirects",
        None, None,
        "informational: many admins disable this, but treatment depends on IPv6 use on the host",
    ),
    (
        "net.ipv4.conf.all.rp_filter",
        None, None,
        "informational: 0 can be valid on routers or asymmetric networks; 1/2 are stricter",
    ),
]

_PERF_PARAMS = [
    # swappiness > 60 is unusual on a server; just report the value
    ("vm.swappiness", None, None, ""),
    # overcommit: 0=heuristic 1=always 2=strict
    ("vm.overcommit_memory", None, None, ""),
]


def _sysctl(key: str):
    """Read a sysctl value directly from /proc/sys. Returns str or None."""
    path = "/proc/sys/" + key.replace(".", "/")
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def check() -> Result:
    """Kernel security hardening and performance sysctl parameters."""
    details = []
    status = "OK"
    issues = []

    # Security checks
    for key, expected, sev, desc in _SECURITY_PARAMS:
        val = _sysctl(key)
        if val is None:
            continue   # key not present on this kernel — skip silently

        if expected is not None and val != expected:
            issues.append(f"{key} = {val}  (expected {expected}) — {desc}")
            if sev:
                status = escalate(status, sev)
        else:
            details.append(f"{key} = {val}  OK")

    for key, _, _, desc in _CONTEXT_PARAMS:
        val = _sysctl(key)
        if val is None:
            continue
        note = ""
        if key == "fs.suid_dumpable":
            meanings = {"0": "disabled", "1": "enabled", "2": "suidsafe/systemd-coredump style"}
            note = f"  ({meanings.get(val, 'custom')})"
        elif key == "kernel.kptr_restrict":
            try:
                if int(val) >= 1:
                    note = "  (hardened)"
                else:
                    note = "  (less strict)"
            except ValueError:
                pass
        elif key == "kernel.dmesg_restrict":
            note = "  (restricted)" if val == "1" else "  (unrestricted)"
        elif key == "net.ipv4.conf.all.rp_filter":
            meanings = {"0": "disabled/context-dependent", "1": "strict", "2": "loose"}
            note = f"  ({meanings.get(val, 'custom')})"
        elif key == "net.ipv6.conf.all.accept_redirects":
            note = "  (disabled)" if val == "0" else "  (enabled/context-dependent)"
        details.append(f"{key} = {val}{note} — {desc}")

    # Informational performance/tuning values (never change status)
    for key, _, _, _ in _PERF_PARAMS:
        val = _sysctl(key)
        if val is None:
            continue
        note = ""
        if key == "vm.swappiness":
            try:
                sv = int(val)
                if sv > 60:
                    note = "  (high — consider lowering on servers)"
                elif sv == 0:
                    note = "  (no swap — OOM killer will trigger earlier)"
            except ValueError:
                pass
        if key == "vm.overcommit_memory":
            meanings = {"0": "heuristic", "1": "always-overcommit", "2": "strict"}
            note = f"  ({meanings.get(val, 'unknown')})"
        details.append(f"{key} = {val}{note}")

    details = issues + details

    if status == "OK":
        msg = f"Kernel security parameters look reasonable ({len(details)} checked)"
    else:
        msg = f"{len(issues)} high-signal sysctl issue(s)"

    return Result(
        name="sysctl",
        status=status,
        message=msg,
        details=details,
        remediation=(
            "Review and set parameters in /etc/sysctl.d/99-hardening.conf, "
            "then run: sysctl --system"
        ) if status != "OK" else None,
    )
