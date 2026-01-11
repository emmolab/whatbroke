import argparse
import sys

from checks import discover_checks
from result import Result

SEVERITY = {"OK": 0, "WARN": 1, "BROKE": 2, "CRIT": 3}

# ANSI color codes
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def get_color_for_status(status):
    color_map = {
        "OK": Colors.GREEN,
        "WARN": Colors.YELLOW, 
        "BROKE": Colors.MAGENTA,
        "CRIT": Colors.RED
    }
    return color_map.get(status, Colors.WHITE)

def print_header():
    header = f"""
{Colors.BOLD}{Colors.CYAN}
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   __          ___           _   ____            _                            ║
║   \ \        / / |         | | |  _ \          | |                           ║
║    \ \  /\  / /| |__   __ _| |_| |_) |_ __ ___ | | _____                     ║
║     \ \/  \/ / | '_ \ / _` | __|  _ <| '__/ _ \| |/ / _ \                    ║
║      \  /\  /  | | | | (_| | |_| |_) | | | (_) |   <  __/                    ║
║       \/  \/   |_| |_|\__,_|\__|____/|_|  \___/|_|\_\___|                    ║
║                                                                              ║
║                    Find what's broken.   Fix what matters.                   ║
║                                                                              ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
{Colors.END}
"""
    print(header)


def main():
    p = argparse.ArgumentParser(prog="whatbroke")
    p.add_argument("--compact", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--only")
    p.add_argument("--skip")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = p.parse_args()

    # Disable colors if requested
    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith('_'):
                setattr(Colors, attr, '')

    if not args.compact and not args.json:
        print_header()

    checks = discover_checks()

    if args.only:
        allow = set(args.only.split(","))
        checks = {k: v for k, v in checks.items() if k in allow}

    if args.skip:
        skip = set(args.skip.split(","))
        checks = {k: v for k, v in checks.items() if k not in skip}

    results = []

    for name, fn in checks.items():
        try:
            results.append(fn())
        except Exception as e:
            results.append(Result(name, "CRIT", "check failed", [str(e)]))

    worst = "OK"
    for r in results:
        if SEVERITY[r.status] > SEVERITY[worst]:
            worst = r.status

    if args.compact:
        bad = [r for r in results if r.status != "OK"]
        if not bad:
            print(f"{Colors.GREEN}OK{Colors.END}")
        else:
            for r in bad:
                color = get_color_for_status(r.status)
                print(f"{r.name}:{color}{r.status}{Colors.END}")
        sys.exit(SEVERITY[worst])

    if args.json:
        import json
        json_results = []
        for r in results:
            json_results.append({
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "details": r.details,
                "remediation": r.remediation
            })
        print(json.dumps(json_results, indent=2))
        sys.exit(SEVERITY[worst])

    for r in results:
        color = get_color_for_status(r.status)
        print(f"{Colors.BOLD}{r.name}{Colors.END}: {color}{r.status}{Colors.END} - {r.message}")
        if args.verbose and r.details:
            for d in r.details:
                print(f"  {Colors.CYAN}•{Colors.END} {d}")
        if args.verbose and r.remediation:
            print(f"  {Colors.YELLOW}→{Colors.END} {Colors.BOLD}Fix:{Colors.END} {r.remediation}")
        print()  # Add spacing between results

    # Print summary
    print(f"{Colors.BOLD}Summary:{Colors.END} Overall system status is {get_color_for_status(worst)}{worst}{Colors.END}")
    sys.exit(SEVERITY[worst])


if __name__ == "__main__":
    main()
