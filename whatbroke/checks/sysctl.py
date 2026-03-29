from ..result import Result, escalate

# Each entry: (sysctl_key, expected, severity_if_wrong, description)
# expected=None means "just report the value" (informational)
_SECURITY_PARAMS = [
    ("kernel.randomize_va_space",
     "2",    "WARN",
     "ASLR not fully enabled (should be 2)"),

    ("fs.suid_dumpable",
     "0",    "WARN",
     "SUID core dumps enabled — privileged process memory may leak"),

    ("kernel.dmesg_restrict",
     "1",    "WARN",
     "dmesg readable by unprivileged users"),

    ("kernel.kptr_restrict",
     None,   "WARN",
     "kernel pointer exposure (should be >= 1)"),

    ("net.ipv4.tcp_syncookies",
     "1",    "WARN",
     "TCP SYN cookie protection disabled — host vulnerable to SYN flood"),

    ("net.ipv4.conf.all.accept_redirects",
     "0",    "WARN",
     "ICMP redirect acceptance enabled — routing can be manipulated"),

    ("net.ipv4.conf.default.accept_redirects",
     "0",    "WARN",
     "ICMP redirect acceptance enabled on new interfaces"),

    ("net.ipv6.conf.all.accept_redirects",
     "0",    "WARN",
     "IPv6 ICMP redirect acceptance enabled"),

    ("net.ipv4.conf.all.rp_filter",
     "1",    "WARN",
     "Reverse path filtering disabled — IP spoofing easier"),
]

_PERF_PARAMS = [
    # swappiness > 60 is unusual on a server; just report the value
    ("vm.swappiness",           None, None, ""),
    # overcommit: 0=heuristic 1=always 2=strict
    ("vm.overcommit_memory",    None, None, ""),
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
    status  = "OK"
    issues  = []

    # Security checks
    for key, expected, sev, desc in _SECURITY_PARAMS:
        val = _sysctl(key)
        if val is None:
            continue   # key not present on this kernel — skip silently

        # Custom logic for kptr_restrict (want >= 1, not exactly "1")
        if key == "kernel.kptr_restrict":
            try:
                if int(val) < 1:
                    issues.append(f"{key} = {val}  — {desc}")
                    status = escalate(status, sev)
                else:
                    details.append(f"{key} = {val}  OK")
            except ValueError:
                pass
            continue

        if expected is not None and val != expected:
            issues.append(f"{key} = {val}  (expected {expected}) — {desc}")
            status = escalate(status, sev)
        else:
            details.append(f"{key} = {val}  OK")

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

    # Put issues at the top of details
    details = issues + details

    if status == "OK":
        msg = f"Kernel security parameters look hardened ({len(details)} checked)"
    else:
        msg = f"{len(issues)} sysctl misconfiguration(s)"

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
