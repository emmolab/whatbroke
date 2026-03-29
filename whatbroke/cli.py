import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    BOLD     = '\033[1m'
    END      = '\033[0m'


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


_BANNER = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   __          ___           _   ____            _                            ║
║   \ \        / / |         | | |  _ \          | |                           ║
║    \ \  /\  / /| |__   __ _| |_| |_) |_ __ ___ | | _____                    ║
║     \ \/  \/ / | '_ \ / _` | __|  _ <| '__/ _ \| |/ / _ \                   ║
║      \  /\  /  | | | | (_| | |_| |_) | | | (_) |   <  __/                   ║
║       \/  \/   |_| |_|\__,_|\__|____/|_|  \___/|_|\_\___|                   ║
║                                                                              ║
║                   Find what's broken.  Fix what matters.                     ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def _print_header() -> None:
    print(Colors.BOLD + Colors.CYAN + _BANNER + Colors.END)


def _run_one(name: str, fn) -> Result:
    try:
        return fn()
    except Exception as exc:
        return Result(name, "CRIT", "check raised an exception", [str(exc)])


def _print_result(r: Result, verbose: bool) -> None:
    c = _color(r.status)
    print(f"{Colors.BOLD}{r.name}{Colors.END}: {c}{r.status}{Colors.END}  {r.message}")
    if verbose:
        for d in r.details:
            print(f"  {Colors.CYAN}•{Colors.END} {d}")
        if r.remediation:
            print(f"  {Colors.YELLOW}→ Fix:{Colors.END} {r.remediation}")
    print()


def main() -> None:
    from . import __version__

    p = argparse.ArgumentParser(prog="whatbroke",
                                description="Linux system diagnostics tool")
    p.add_argument("--version", action="version", version=f"whatbroke {__version__}")
    p.add_argument("--compact", action="store_true",
                   help="One line per broken check (good for scripts/cron)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show details and remediation hints")
    p.add_argument("--only", metavar="CHECK,...",
                   help="Run only the specified checks (comma-separated)")
    p.add_argument("--skip", metavar="CHECK,...",
                   help="Skip the specified checks (comma-separated)")
    p.add_argument("--json", action="store_true",
                   help="Output results as JSON")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colour output")
    args = p.parse_args()

    if args.no_color:
        _disable_colors()

    if not args.compact and not args.json:
        _print_header()

    checks = discover_checks()

    if args.only:
        allow = set(args.only.split(","))
        checks = {k: v for k, v in checks.items() if k in allow}

    if args.skip:
        skip = set(args.skip.split(","))
        checks = {k: v for k, v in checks.items() if k not in skip}

    # ── Run all checks in parallel ──────────────────────────────────────────
    # Each check is independent (reads files / runs subprocesses) so
    # thread-parallelism is safe and cuts total runtime to ~max(check times)
    # instead of sum(check times).  Cap workers at 8 to avoid spawning too
    # many subprocesses at once on resource-constrained machines.
    t_start = time.monotonic()
    results_map: dict = {}

    with ThreadPoolExecutor(max_workers=min(len(checks), 8)) as pool:
        futures = {pool.submit(_run_one, name, fn): name
                   for name, fn in checks.items()}

        # In pretty non-verbose mode print each result as it arrives so the
        # operator sees fast checks (hardware, services) immediately while
        # slow ones (logs, security/apt, networking) are still running.
        if not args.compact and not args.json and not args.verbose:
            for fut in as_completed(futures):
                r = fut.result()
                results_map[r.name] = r
                _print_result(r, verbose=False)
        else:
            for fut in as_completed(futures):
                r = fut.result()
                results_map[r.name] = r

    elapsed = time.monotonic() - t_start

    # Sort results alphabetically for consistent ordering in all output modes.
    results = [results_map[name] for name in sorted(results_map)]

    worst = max(results, key=lambda r: SEVERITY[r.status]).status \
            if results else "OK"

    # ── compact ─────────────────────────────────────────────────────────────
    if args.compact:
        bad = [r for r in results if r.status != "OK"]
        if not bad:
            print(f"{Colors.GREEN}OK{Colors.END}")
        else:
            for r in bad:
                c = _color(r.status)
                print(f"{r.name}:{c}{r.status}{Colors.END} {r.message}")
        sys.exit(SEVERITY[worst])

    # ── JSON ────────────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps([
            {
                "name":        r.name,
                "status":      r.status,
                "message":     r.message,
                "details":     r.details,
                "remediation": r.remediation,
            }
            for r in results
        ], indent=2))
        sys.exit(SEVERITY[worst])

    # ── verbose: print all results in sorted order with details ─────────────
    if args.verbose:
        for r in results:
            _print_result(r, verbose=True)

    # ── summary line ────────────────────────────────────────────────────────
    c = _color(worst)
    n_bad = sum(1 for r in results if r.status != "OK")
    summary = f"{Colors.BOLD}Overall:{Colors.END} {c}{worst}{Colors.END}"
    if n_bad:
        summary += f"  ({n_bad} check{'s' if n_bad != 1 else ''} need attention)"
    summary += f"  {Colors.BLUE}{elapsed:.1f}s{Colors.END}"
    print(summary)

    sys.exit(SEVERITY[worst])


if __name__ == "__main__":
    main()
