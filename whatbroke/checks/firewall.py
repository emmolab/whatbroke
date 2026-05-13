import os
import pathlib
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
    return any(kw in stderr.lower() for kw in ("permitted", "permission denied", "must be root", "you need to be root"))


def _ufw_enabled_in_config() -> bool:
    try:
        conf = pathlib.Path("/etc/ufw/ufw.conf")
        return conf.exists() and "enabled=yes" in conf.read_text().lower()
    except OSError:
        return False


def _probe_nftables():
    """Return (active: bool | None, rule_count: int|None, detail: str)."""
    if not shutil.which("nft"):
        return False, None, ""
    rc, out, err = _run(["nft", "list", "ruleset"])
    if rc != 0:
        if _needs_root(err):
            return None, None, "nftables: installed (ruleset requires root to inspect)"
        return False, None, ""
    lines = [l for l in out.splitlines() if l.strip() and not l.strip().startswith("#")]
    rules = sum(1 for l in lines if any(
        kw in l for kw in ("accept", "drop", "reject", "log", "counter", "masquerade", "dnat", "snat")
    ))
    active = rules > 0 or "table" in out
    return active, rules, f"nftables: {rules} rule(s)"


def _probe_iptables():
    """Return (active: bool | None, rule_count: int|None, detail: str)."""
    if not shutil.which("iptables"):
        return False, None, ""
    rc, out, err = _run(["iptables", "-L", "-n", "--line-numbers"], timeout=15)
    if rc != 0:
        if _needs_root(err):
            return None, None, "iptables: installed (requires root to inspect)"
        return False, None, ""
    rules = sum(1 for l in out.splitlines() if l and l[0].isdigit())
    chains = [l for l in out.splitlines() if l.startswith("Chain")]
    all_accept_empty = all("policy ACCEPT" in l for l in chains) and rules == 0
    active = not all_accept_empty
    return active, rules, f"iptables: {rules} non-default rule(s)"


def _probe_ufw():
    """Return (active: bool | None, detail: str)."""
    if not shutil.which("ufw"):
        return None, ""

    # UFW prints a stable first line: "Status: active" / "Status: inactive".
    # Try a couple of variants because some hosts behave differently under sudo.
    for cmd in (["ufw", "status"], ["ufw", "status", "verbose"]):
        rc, out, err = _run(cmd)
        first = out.splitlines()[0].strip() if out.strip() else ""
        if rc == 0 and first:
            first_l = first.lower()
            if "status:" in first_l:
                if "inactive" in first_l:
                    return False, "ufw: inactive"
                if "active" in first_l:
                    return True, "ufw: active"
            if "inactive" in first_l:
                return False, "ufw: inactive"
            if "active" in first_l:
                return True, "ufw: active"
        if _needs_root(f"{out}\n{err}"):
            break

    service_running = _service_active("ufw")
    enabled_in_config = _ufw_enabled_in_config()
    running_as_root = getattr(os, "geteuid", lambda: 1)() == 0

    if service_running or enabled_in_config:
        if running_as_root:
            if service_running:
                return True, "ufw: active (service running; status command unavailable)"
            return True, "ufw: enabled in /etc/ufw/ufw.conf"
        return None, "ufw: installed/enabled (run with sudo to confirm live status)"

    if not running_as_root:
        return None, "ufw: installed (run with sudo to inspect status)"

    return False, "ufw: inactive"


def _probe_firewalld():
    """Return (active: bool | None, detail: str) or None if firewalld not present."""
    if not _service_active("firewalld"):
        # Check if installed but not running
        rc, _, _ = _run(["systemctl", "cat", "firewalld.service"])
        if rc != 0:
            return None, ""
        return False, "firewalld: installed but not running"

    if not shutil.which("firewall-cmd"):
        return None, "firewalld: service active (firewall-cmd unavailable to confirm state)"

    rc, out, err = _run(["firewall-cmd", "--state"])
    state = out.strip().lower()
    if rc == 0 and "running" in state:
        return True, "firewalld: running"
    if _needs_root(f"{out}\n{err}"):
        return None, "firewalld: service active (run with sudo to confirm daemon state)"
    return None, "firewalld: service active (daemon state lookup failed)"


# ── Main check ────────────────────────────────────────────────────────────────

def check() -> Result:
    """Firewall status (nftables, iptables, ufw, firewalld)."""
    details = []
    issues = []
    inactive = []
    status = "OK"

    found_any = False
    firewall_active = False
    firewall_unconfirmed = False
    unconfirmed_commands: list[str] = []

    # nftables
    nft_active, nft_rules, nft_detail = _probe_nftables()
    if nft_detail:
        found_any = True
        if nft_active is True:
            firewall_active = True
        elif nft_active is None:
            firewall_unconfirmed = True
            unconfirmed_commands.append("  nftables:  sudo nft list ruleset")
        details.append(nft_detail)

    # ufw
    ufw_active, ufw_detail = _probe_ufw()
    if ufw_detail:
        found_any = True
        if ufw_active is True:
            firewall_active = True
        elif ufw_active is None:
            firewall_unconfirmed = True
            unconfirmed_commands.append("  ufw:       sudo ufw status verbose")
        if ufw_active is False:  # explicitly inactive (not just unknown)
            inactive.append(ufw_detail)
        else:
            details.append(ufw_detail)

    # firewalld
    fwd_active, fwd_detail = _probe_firewalld()
    if fwd_detail:
        found_any = True
        if fwd_active is True:
            firewall_active = True
        elif fwd_active is None:
            firewall_unconfirmed = True
            unconfirmed_commands.append("  firewalld: sudo firewall-cmd --state")
        if fwd_active is False:
            inactive.append(fwd_detail)
        else:
            details.append(fwd_detail)

    # iptables remains worth checking when nftables is absent, inactive, or
    # merely unconfirmed. Skip it only once nftables is clearly active so we do
    # not hide legacy iptables rules on mixed-tool hosts.
    if nft_active is not True:
        ipt_active, ipt_rules, ipt_detail = _probe_iptables()
        if ipt_detail:
            found_any = True
            if ipt_active is True:
                firewall_active = True
                details.append(ipt_detail)
            elif ipt_active is None:
                firewall_unconfirmed = True
                unconfirmed_commands.append("  iptables:  sudo iptables -L -n --line-numbers")
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

    remediation = None
    if not firewall_active:
        status = escalate(status, "WARN")
        if firewall_unconfirmed:
            issues.insert(0, "Firewall present but live status could not be confirmed without privilege")
            commands = "\n".join(dict.fromkeys(unconfirmed_commands)) or "  sudo nft list ruleset"
            remediation = (
                "Re-run with sudo before changing firewall state:\n"
                f"{commands}\n"
                "If no live firewall is confirmed, then enable one backend deliberately."
            )
            details.extend(inactive)
        else:
            issues.insert(0, "No active firewall rules detected")
            remediation = (
                "Enable a firewall:\n"
                "  nftables:  systemctl enable --now nftables\n"
                "  ufw:       ufw enable\n"
                "  firewalld: systemctl enable --now firewalld"
            )
            issues.extend(inactive)
    else:
        details.extend(f"{line}  (inactive backend, another firewall appears active)" for line in inactive)

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
        remediation=remediation,
    )
