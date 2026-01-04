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
    "CRIT": 3,
}

COLORS = {
    "OK": "\033[32m",      # Green
    "WARN": "\033[33m",     # Yellow
    "BROKE": "\033[31m",    # Red
    "CRIT": "\033[35m",     # Magenta/Purple
    "RESET": "\033[0m",
}

def color(text, status, enable):
    if not enable:
        return text
    return f"{COLORS[status]}{text}{COLORS['RESET']}"

def main():
    parser = argparse.ArgumentParser(
        prog="whatbroke",
        description="🔧 Comprehensive Linux system diagnostics tool",
        epilog="📊 Checks 8 categories: Disk, Hardware, Services, Containers, Networking, Logs, Security, Scheduled Tasks"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="🔍 Show detailed output and remediation steps")
    parser.add_argument("--json", action="store_true", help="📄 Output in JSON format for automation")
    parser.add_argument("--only", help="🎯 Run only specific checks (comma-separated)")
    parser.add_argument("--skip", help="⏭ Skip specific checks (comma-separated)")
    parser.add_argument("--no-color", action="store_true", help="🎨 Disable colored output")
    parser.add_argument("--compact", action="store_true", help="📱 Compact output format")
    args = parser.parse_args()

    # Header for non-JSON output
    if not args.json and not args.compact:
        print(f"{COLORS['OK']}{'='*60}{COLORS['RESET']}")
        print(f"{COLORS['OK']}🔧 whatbroke System Health Monitor v0.1.0{COLORS['RESET']}")
        print(f"{COLORS['OK']}{'='*60}{COLORS['RESET']}")
        print()

    checks = discover_checks()

    if args.only:
        allowed = set(args.only.split(","))
        checks = {k: v for k, v in checks.items() if k in allowed}
        if not args.json:
            print(f"\033[1;33m🎯 Running: {', '.join(allowed)}\033[0m")

    if args.skip:
        skipped = set(args.skip.split(","))
        checks = {k: v for k, v in checks.items() if k not in skipped}
        if not args.json:
            print(f"\033[1;31m⏭ Skipping: {', '.join(skipped)}\033[0m")

    results = []
    for name, check in checks.items():
        if not args.compact and not args.json:
            print(f"\033[1;36m🔍 Checking: {name.upper()}\033[0m")
        
        try:
            result = check()
            results.append(result)
            
            if not args.compact and not args.json:
                status_emoji = {
                    "OK": "🟢",
                    "WARN": "🟡", 
                    "BROKE": "🔴",
                    "CRIT": "🟣"
                }.get(result.status, "❓")
                
                print(f"  {status_emoji} {result.name}: {result.message}")
        except Exception as e:
            error_result = Result(
                name=name,
                status="CRIT",
                message="💥 Check crashed",
                details=[str(e)],
            )
            results.append(error_result)
            
            if not args.compact and not args.json:
                print(f"  🟣 {name}: 💥 Check crashed - {str(e)[:50]}")

    # Calculate worst status
    worst = "OK"
    for r in results:
        if SEVERITY_EXIT_CODES[r.status] > SEVERITY_EXIT_CODES[worst]:
            worst = r.status

    # Summary (unless compact mode)
            # Compact mode summary
            if args.compact:
                failed_checks = [r for r in results if r.status in ["BROKE", "CRIT"]]
                warn_checks = [r for r in results if r.status == "WARN"]
                
                print(f"{COLORS['OK']}📊 {len(results)} checks: {len(failed_checks)} failed, {len(warn_checks)} warnings{COLORS['RESET']}")
                
                # Show only failed/critical checks in compact mode
                for r in failed_checks[:3]:
                    print(f"  {COLORS['CRIT']}✗ {r.name}: {r.message}{COLORS['RESET']}")
                
                # Show warnings if verbose or no critical issues
                if args.verbose or not failed_checks:
                    for r in warn_checks[:3]:
                        print(f"  {COLORS['WARN']}⚠ {r.name}: {r.message}{COLORS['RESET']}")
            
            # Detailed mode (normal output)
            elif not args.compact:
                status_counts = {}
                for r in results:
                    status_counts[r.status] = status_counts.get(r.status, 0) + 1
                
                summary_parts = []
                for status in ["OK", "WARN", "BROKE", "CRIT"]:
                    count = status_counts.get(status, 0)
                    if count > 0:
                        summary_parts.append(f"{status}: {count}")
                
                print(f"{COLORS['OK']}📊 Summary: {' | '.join(summary_parts)}{COLORS['RESET']}")
                
                # Issues detail
                if worst in ["WARN", "BROKE", "CRIT"] or args.verbose:
                    warn_results = [r for r in results if r.status == "WARN"]
                    error_results = [r for r in results if r.status in ["BROKE", "CRIT"]]
                    
                    if error_results:
                        print(f"{COLORS['CRIT']}🚨 CRITICAL ISSUES ({len(error_results)}):{COLORS['RESET']}")
                        for r in error_results[:3]:  # Show first 3
                            print(f"  {COLORS['CRIT']}• {r.name}: {r.message}{COLORS['RESET']}")
                            if args.verbose and r.remediation:
                                print(f"    {COLORS['WARN']}💡 {r.remediation}{COLORS['RESET']}")
                    
                    if warn_results:
                        print(f"{COLORS['WARN']}⚠️  WARNINGS ({len(warn_results)}):{COLORS['RESET']}")
                        for r in warn_results[:3]:  # Show first 3
                            print(f"  {COLORS['WARN']}• {r.name}: {r.message}{COLORS['RESET']}")
                            if args.verbose and r.remediation:
                                print(f"    {COLORS['WARN']}💡 {r.remediation}{COLORS['RESET']}")
                    print()
        
        print("\033[1;34m" + "="*40 + "\033[0m")

    # Exit with appropriate code
    if not args.json and not args.compact:
        worst_emoji = {"OK": "🟢", "WARN": "🟡", "BROKE": "🔴", "CRIT": "🟣"}[worst]
        print(f"\033[1m🚪 Exit Status: {worst_emoji} {worst} (code {SEVERITY_EXIT_CODES[worst]})\033[0m")

    sys.exit(SEVERITY_EXIT_CODES[worst])

if __name__ == "__main__":
    main()
