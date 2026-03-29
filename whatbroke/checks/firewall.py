import shutil
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "", ""


def _service_active(name: str) -> bool:
    rc, _, _ = _run(["systemctl", "is-active", "--quiet", name])
    return rc == 0


# ── Backend probes ────────────────────────────────────────────────────────────

def _needs_root(stderr: str) -> bool:
    return any(kw in stderr.lower() for kw in ("permitted", "permission denied", "root"))


def _probe_nftables():
    """Return (active: bool, rule_count: int|None, detail: str)."""
    if not shutil.which("nft"):
        return False, None, ""
    rc, out, err = _run(["nft", "list", "ruleset"])
    if rc != 0:
        if _needs_root(err):
            return True, None, "nftables: installed (ruleset requires root to inspect)"
        return False, None, ""
    lines = [l for l in out.splitlines() if l.strip() and not l.strip().startswith("#")]
    rules = sum(1 for l in lines if any(
        kw in l for kw in ("accept", "drop", "reject", "log", "counter", "masquerade", "dnat", "snat")
    ))
    active = rules > 0 or "table" in out
    return active, rules, f"nftables: {rules} rule(s)"


def _probe_iptables():
    """Return (active: bool, rule_count: int|None, detail: str)."""
    if not shutil.which("iptables"):
        return False, None, ""
    rc, out, err = _run(["iptables", "-L", "-n", "--line-numbers"], timeout=15)
    if rc != 0:
        if _needs_root(err):
            return True, None, "iptables: installed (requires root to inspect)"
        return False, None, ""
    rules = sum(1 for l in out.splitlines() if l and l[0].isdigit())
    chains = [l for l in out.splitlines() if l.startswith("Chain")]
    all_accept_empty = all("policy ACCEPT" in l for l in chains) and rules == 0
    active = not all_accept_empty
    return active, rules, f"iptables: {rules} non-default rule(s)"


def _probe_ufw():
    """Return (active: bool, detail: str) or None if ufw not present."""
    if not shutil.which("ufw"):
        return None, ""
    rc, out, err = _run(["ufw", "status"])
    if rc != 0:
        if _needs_root(err + out):
            return True, "ufw: installed (requires root to read status)"
        return None, ""
    first = out.splitlines()[0] if out.strip() else ""
    active = "active" in first.lower() and "inactive" not in first.lower()
    return active, f"ufw: {'active' if active else 'inactive'}"


def _probe_firewalld():
    """Return (active: bool, detail: str) or None if firewalld not present."""
    if not _service_active("firewalld"):
        # Check if installed but not running
        rc, _, _ = _run(["systemctl", "cat", "firewalld.service"])
        if rc != 0:
            return None, ""
        return False, "firewalld: installed but not running"
    rc, out, _ = _run(["firewall-cmd", "--state"])
    active = rc == 0 and "running" in out.lower()
    return active, f"firewalld: {'running' if active else 'not running'}"


# ── Main check ────────────────────────────────────────────────────────────────

def check() -> Result:
    """Firewall status (nftables, iptables, ufw, firewalld)."""
    details = []
    issues = []
    status = "OK"

    found_any = False
    firewall_active = False

    # nftables
    nft_active, nft_rules, nft_detail = _probe_nftables()
    if nft_detail:
        found_any = True
        if nft_active:
            firewall_active = True
        details.append(nft_detail)

    # ufw
    ufw_active, ufw_detail = _probe_ufw()
    if ufw_detail:
        found_any = True
        if ufw_active:
            firewall_active = True
        if ufw_active is False:  # explicitly inactive (not just unknown)
            issues.append(f"{ufw_detail}")
        else:
            details.append(ufw_detail)

    # firewalld
    fwd_active, fwd_detail = _probe_firewalld()
    if fwd_detail:
        found_any = True
        if fwd_active:
            firewall_active = True
        if fwd_active is False:
            issues.append(fwd_detail)
        else:
            details.append(fwd_detail)

    # iptables (skip if nftables present — nft supersedes iptables on modern systems)
    if not nft_detail:
        ipt_active, ipt_rules, ipt_detail = _probe_iptables()
        if ipt_detail:
            found_any = True
            if ipt_active:
                firewall_active = True
            if ipt_active:
                details.append(ipt_detail)
            else:
                details.append(f"{ipt_detail}  (default ACCEPT, no rules)")

    if not found_any:
        return Result(
            name="firewall",
            status="WARN",
            message="No firewall tooling detected (nft/iptables/ufw/firewalld)",
            remediation="Install and enable a firewall: nftables, ufw, or firewalld",
        )

    if not firewall_active:
        status = escalate(status, "WARN")
        issues.insert(0, "No active firewall rules detected")

    all_details = issues + details

    if status == "OK":
        msg = "Firewall active"
    else:
        msg = "; ".join(issues) if issues else "Firewall status unclear"

    return Result(
        name="firewall",
        status=status,
        message=msg,
        details=all_details,
        remediation=(
            "Enable a firewall:\n"
            "  nftables:  systemctl enable --now nftables\n"
            "  ufw:       ufw enable\n"
            "  firewalld: systemctl enable --now firewalld"
        ) if status != "OK" else None,
    )
