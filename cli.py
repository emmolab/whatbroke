import argparse
import json
import os
import sys

# Add the project root to Python path for local development
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from result import Result
from checks import discover_checks

SEVERITY_EXIT_CODES = {
    "OK": 0,
    "WARN": 1,
    "BROKE": 2,
}

COLORS = {
    "OK": "\033[32m",
    "WARN": "\033[33m",
    "BROKE": "\033[31m",
    "RESET": "\033[0m",
}

def color(text, status, enable):
    if not enable:
        return text
    return f"{COLORS[status]}{text}{COLORS['RESET']}"

def main():
    parser = argparse.ArgumentParser(prog="whatbroke")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", help="Comma-separated list of checks")
    parser.add_argument("--skip", help="Comma-separated list of checks")
    args = parser.parse_args()

    checks = discover_checks()

    if args.only:
        allowed = set(args.only.split(","))
        checks = {k: v for k, v in checks.items() if k in allowed}

    if args.skip:
        skipped = set(args.skip.split(","))
        checks = {k: v for k, v in checks.items() if k not in skipped}

    results = []
    for name, check in checks.items():
        try:
            results.append(check())
        except Exception as e:
            results.append(
                Result(
                    name=name,
                    status="BROKE",
                    message="Check crashed",
                    details=[str(e)],
                )
            )

    worst = "OK"
    for r in results:
        if SEVERITY_EXIT_CODES[r.status] > SEVERITY_EXIT_CODES[worst]:
            worst = r.status

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        use_color = sys.stdout.isatty()
        for r in results:
            line = f"[{r.status}] {r.name}: {r.message}"
            print(color(line, r.status, use_color))

            if args.verbose:
                for d in r.details:
                    print(f"  - {d}")
                if r.remediation:
                    print(f"    Fix: {r.remediation}")

    sys.exit(SEVERITY_EXIT_CODES[worst])

if __name__ == "__main__":
    main()
