import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .checks import discover_checks
from .result import Result, SEVERITY


class Colors:
    RED      = '\033[91m'
    GREEN    = '\033[92m'
    YELLOW   = '\033[93m'
    BLUE     = '\033[94m'
    MAGENTA  = '\033[95m'
    CYAN     = '\033[96m'
    WHITE    = '\033[97m'
    DIM      = '\033[2m'
    BOLD     = '\033[1m'
    END      = '\033[0m'
    CLEAR    = '\033[2J\033[H'   # clear screen + move cursor home


def _color(status: str) -> str:
    return {
        "OK":    Colors.GREEN,
        "WARN":  Colors.YELLOW,
        "BROKE": Colors.MAGENTA,
        "CRIT":  Colors.RED,
    }.get(status, Colors.WHITE)


def _disable_colors() -> None:
    for attr in vars(Colors):
        if not attr.startswith('_'):
            setattr(Colors, attr, '')


_BANNER = (
    "WhatBroke\n"
    "Find what's broken. Fix what matters.\n"
)

# ── State file (tracks first-seen timestamps for issues) ─────────────────────

_STATE_DIR  = os.path.expanduser("~/.local/share/whatbroke")
_STATE_FILE = os.path.join(_STATE_DIR, "state.json")


def _normalize_state(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {"checks": {}}

    checks = raw.get("checks") if isinstance(raw.get("checks"), dict) else raw
    normalized = {}
    for name, entry in checks.items():
        if not isinstance(entry, dict):
            continue
        normalized[name] = {
            "status": entry.get("status", "OK"),
            "message": entry.get("message", ""),
            "first_seen": entry.get("first_seen"),
            "last_seen": entry.get("last_seen"),
        }
    return {
        "updated_at": raw.get("updated_at"),
        "checks": normalized,
    }


def _load_state() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return _normalize_state(json.load(f))
    except (OSError, json.JSONDecodeError):
        return {"checks": {}}


def _compare_state(results: list[Result], previous: dict) -> dict:
    old_checks = previous.get("checks", {})
    changes = {
        "new": set(),
        "resolved": set(),
        "worsened": set(),
        "improved": set(),
        "changed": set(),
        "previous": {},
    }

    current_names = {r.name for r in results}
    for r in results:
        prior = old_checks.get(r.name)
        if not prior:
            if r.status != "OK":
                changes["new"].add(r.name)
                changes["changed"].add(r.name)
            continue

        prior_status = prior.get("status", "OK")
        prior_message = prior.get("message", "")
        if prior_status == r.status and prior_message == r.message:
            continue

        changes["changed"].add(r.name)
        changes["previous"][r.name] = prior
        if prior_status == "OK" and r.status != "OK":
            changes["new"].add(r.name)
        elif prior_status != "OK" and r.status == "OK":
            changes["resolved"].add(r.name)
        elif SEVERITY[r.status] > SEVERITY[prior_status]:
            changes["worsened"].add(r.name)
        elif SEVERITY[r.status] < SEVERITY[prior_status]:
            changes["improved"].add(r.name)

    for name, prior in old_checks.items():
        if name in current_names:
            continue
        if prior.get("status", "OK") != "OK":
            changes["resolved"].add(name)

    return changes


def _save_state(results: list[Result], previous: dict | None = None) -> dict:
    """Persist current check statuses; return transition summary for this run."""
    now = datetime.now(timezone.utc).isoformat()
    old = previous or _load_state()
    changes = _compare_state(results, old)

    new_checks = {}
    for r in results:
        prior = old.get("checks", {}).get(r.name, {})
        first_seen = now if r.status != "OK" and prior.get("status", "OK") == "OK" else prior.get("first_seen")
        new_checks[r.name] = {
            "status": r.status,
            "message": r.message,
            "first_seen": first_seen,
            "last_seen": now,
        }

    os.makedirs(_STATE_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump({"updated_at": now, "checks": new_checks}, f, indent=2)

    return changes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _severity_key(r: Result) -> int:
    """Higher number = shown first (CRIT=3, WARN=1, OK=0)."""
    return -SEVERITY[r.status]


def _print_header() -> None:
    print(Colors.BOLD + Colors.CYAN + _BANNER + Colors.END)


def _run_one(name: str, fn) -> Result:
    try:
        return fn()
    except Exception as exc:
        return Result(name, "CRIT", "check raised an exception", [str(exc)])


def _transition_tag(name: str, changes: dict) -> str:
    if name in changes["new"]:
        label = "NEW"
    elif name in changes["worsened"]:
        label = "WORSE"
    elif name in changes["improved"]:
        label = "IMPROVED"
    elif name in changes["resolved"]:
        label = "RECOVERED"
    elif name in changes["changed"]:
        label = "CHANGED"
    else:
        return ""
    return f" {Colors.BOLD}{Colors.CYAN}[{label}]{Colors.END}"


def _result_hint(r: Result) -> str | None:
    if r.status == "OK":
        return None
    if r.hint:
        return r.hint

    why = {
        "CRIT": "service availability or data safety may be at risk.",
        "BROKE": "something user-visible is degraded or partially failed.",
        "WARN": "it can turn into an outage if it keeps drifting.",
    }.get(r.status)

    next_step = None
    if r.remediation:
        next_step = next((line.strip() for line in r.remediation.splitlines() if line.strip()), None)

    parts = []
    if why and r.status in {"CRIT", "BROKE"}:
        parts.append(f"Why: {why}")
    if next_step:
        parts.append(f"Next: {next_step}")
    elif r.status == "WARN":
        parts.append("Next: review this check before it escalates.")
    return "  ".join(parts) if parts else None


def _print_result(r: Result, verbose: bool, changes: dict | None = None) -> None:
    c = _color(r.status)
    tag = _transition_tag(r.name, changes or {"new": set(), "worsened": set(), "improved": set(), "resolved": set(), "changed": set()})
    print(f"{Colors.BOLD}{r.name}{Colors.END}: {c}{r.status}{Colors.END}  {r.message}{tag}")

    hint = _result_hint(r)
    if hint:
        print(f"  {Colors.DIM}↳ {hint}{Colors.END}")

    if verbose:
        previous = (changes or {}).get("previous", {}).get(r.name)
        if previous:
            print(f"  {Colors.DIM}was {previous.get('status', 'OK')}: {previous.get('message', '')}{Colors.END}")
        for d in r.details:
            print(f"  {Colors.CYAN}•{Colors.END} {d}")
        if r.remediation:
            print(f"  {Colors.YELLOW}→ Fix:{Colors.END} {r.remediation}")
    print()


def _run_checks(checks: dict, max_workers: int = 8) -> tuple[dict, float]:
    """Run all checks in parallel. Returns (results_map, elapsed_seconds)."""
    t_start = time.monotonic()
    results_map: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(checks), max_workers)) as pool:
        futures = {pool.submit(_run_one, name, fn): name
                   for name, fn in checks.items()}
        for fut in as_completed(futures):
            r = fut.result()
            results_map[r.name] = r
    return results_map, time.monotonic() - t_start


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from . import __version__

    p = argparse.ArgumentParser(prog="whatbroke",
                                description="Linux system diagnostics tool")
    p.add_argument("--version", action="version", version=f"whatbroke {__version__}")

    # Output modes
    p.add_argument("--compact", action="store_true",
                   help="One line per broken check (good for scripts/cron)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show details and remediation hints")
    p.add_argument("-b", "--broken-only", action="store_true",
                   help="Only show checks that are not OK")
    p.add_argument("--json", action="store_true",
                   help="Output results as JSON")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colour output")

    # Filtering
    p.add_argument("--only", metavar="CHECK,...",
                   help="Run only the specified checks (comma-separated)")
    p.add_argument("--skip", metavar="CHECK,...",
                   help="Skip the specified checks (comma-separated)")

    # Behaviour
    p.add_argument("--watch", metavar="SECONDS", type=int, nargs="?", const=5,
                   help="Refresh every N seconds (default 5). Ctrl-C to stop.")
    p.add_argument("--diff", action="store_true",
                   help="Only show checks that are new/newly broken since last run")
    p.add_argument("--no-state", action="store_true",
                   help="Do not read or write the state file (~/.local/share/whatbroke/state.json)")

    args = p.parse_args()

    if args.no_color:
        _disable_colors()

    checks = discover_checks()

    if args.only:
        allow = set(args.only.split(","))
        checks = {k: v for k, v in checks.items() if k in allow}

    if args.skip:
        skip = set(args.skip.split(","))
        checks = {k: v for k, v in checks.items() if k not in skip}

    # ── watch loop ────────────────────────────────────────────────────────────
    if args.watch is not None:
        interval = max(args.watch, 1)
        try:
            while True:
                _run_single(checks, args, watch_interval=interval)
                time.sleep(interval)
        except KeyboardInterrupt:
            print()
            sys.exit(0)
    else:
        sys.exit(_run_single(checks, args))


def _format_change_summary(changes: dict) -> str:
    parts = []
    if changes["new"]:
        parts.append(f"{Colors.CYAN}{len(changes['new'])} new{Colors.END}")
    if changes["worsened"]:
        parts.append(f"{Colors.RED}{len(changes['worsened'])} worse{Colors.END}")
    if changes["improved"]:
        parts.append(f"{Colors.GREEN}{len(changes['improved'])} improved{Colors.END}")
    if changes["resolved"]:
        parts.append(f"{Colors.GREEN}{len(changes['resolved'])} recovered{Colors.END}")
    if not parts:
        return ""
    return "  changed since last run: " + "  ".join(parts)


def _run_single(checks: dict, args, watch_interval: int | None = None) -> int:
    """Run one pass of all checks. Returns exit code."""
    # In watch mode clear the screen before printing
    if watch_interval is not None:
        print(Colors.CLEAR, end="")

    show_banner = not args.compact and not args.json
    if show_banner and watch_interval is None:
        _print_header()

    # ── Run checks ────────────────────────────────────────────────────────────
    results_map, elapsed = _run_checks(checks)

    # Sort by severity (worst first), then alphabetically within same severity
    results = sorted(
        results_map.values(),
        key=lambda r: (-SEVERITY[r.status], r.name),
    )

    worst = max(results, key=lambda r: SEVERITY[r.status]).status \
            if results else "OK"

    # ── State file ────────────────────────────────────────────────────────────
    changes = {"new": set(), "resolved": set(), "worsened": set(), "improved": set(), "changed": set(), "previous": {}}
    if not args.no_state:
        previous_state = _load_state()
        changes = _save_state(results, previous_state)

    # ── compact ───────────────────────────────────────────────────────────────
    if args.compact:
        display = [r for r in results if r.status != "OK"]
        if args.diff:
            display = [r for r in display if r.name in changes["new"] or r.name in changes["worsened"] or r.name in changes["changed"]]
        if not display:
            if not args.diff:
                print(f"{Colors.GREEN}OK{Colors.END}")
            return SEVERITY[worst]
        for r in display:
            c = _color(r.status)
            tag = _transition_tag(r.name, changes)
            print(f"{r.name}:{c}{r.status}{Colors.END} {r.message}{tag}")
        return SEVERITY[worst]

    # ── JSON ──────────────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps([
            {
                "name":        r.name,
                "status":      r.status,
                "message":     r.message,
                "details":     r.details,
                "remediation": r.remediation,
                "hint": _result_hint(r),
                "change": next((label for label, members in [("new", changes["new"]), ("worse", changes["worsened"]), ("improved", changes["improved"]), ("recovered", changes["resolved"]), ("changed", changes["changed"])] if r.name in members), None),
            }
            for r in results
        ], indent=2))
        return SEVERITY[worst]

    # ── pretty output ─────────────────────────────────────────────────────────
    if watch_interval is not None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{Colors.BOLD}{Colors.CYAN}WhatBroke{Colors.END}  "
              f"{Colors.DIM}{ts}  refreshing every {watch_interval}s  "
              f"(Ctrl-C to stop){Colors.END}\n")

    # --diff: show only checks that became broken since last run
    display = results
    if args.diff:
        display = [r for r in results if r.name in changes["new"] or r.name in changes["worsened"] or r.name in changes["changed"]]
        if not display:
            c = _color(worst)
            print(f"{Colors.GREEN}No broken checks changed since last run.{Colors.END}  "
                  f"(overall: {c}{worst}{Colors.END})\n")
            return SEVERITY[worst]

    # --broken-only: hide OK checks
    if args.broken_only:
        display = [r for r in display if r.status != "OK"]
        if not display:
            print(f"{Colors.GREEN}All checks OK.{Colors.END}\n")
            return SEVERITY[worst]

    for r in display:
        _print_result(r, verbose=args.verbose, changes=changes)

    # ── summary ───────────────────────────────────────────────────────────────
    c     = _color(worst)
    n_bad = sum(1 for r in results if r.status != "OK")
    ts    = datetime.now().strftime("%H:%M:%S")

    summary = f"{Colors.BOLD}Overall:{Colors.END} {c}{worst}{Colors.END}"
    if n_bad:
        crit_n = sum(1 for r in results if r.status == "CRIT")
        warn_n = sum(1 for r in results if r.status == "WARN")
        parts  = []
        if crit_n:
            parts.append(f"{Colors.RED}{crit_n} CRIT{Colors.END}")
        if warn_n:
            parts.append(f"{Colors.YELLOW}{warn_n} WARN{Colors.END}")
        summary += "  " + "  ".join(parts)
    summary += (f"  {Colors.DIM}{len(results)} checks  "
                f"{elapsed:.1f}s  {ts}{Colors.END}")
    change_summary = _format_change_summary(changes)
    if change_summary and not args.diff:
        summary += change_summary
    print(summary)

    return SEVERITY[worst]


if __name__ == "__main__":
    main()
