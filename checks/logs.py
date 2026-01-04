import os
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def check():
    proc = subprocess.run(
        ["journalctl", "-p", "3", "-xb", "--no-pager"],
        capture_output=True,
        text=True
    )

    lines = proc.stdout.strip().splitlines()
    if not lines:
        return Result(
            name="logs",
            status="OK",
            message="No critical log entries"
        )

    return Result(
        name="logs",
        status="WARN",
        message="Critical errors found in journal",
        details=lines[:5],
    )
