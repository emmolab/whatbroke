import os
import shutil
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def check():
    if shutil.which('systemctl'):
        proc = subprocess.run(
            ["systemctl", "--failed", "--no-legend"],
            capture_output=True,
            text=True
        )
    else:
        proc = subprocess.run(["echo"], capture_output=True, text=True)
        proc.returncode = 1

    output = proc.stdout.strip()
    if not output:
        return Result(
            name="systemd",
            status="OK",
            message="No failed systemd services"
        )

    services = [line.split()[0] for line in output.splitlines()]

    return Result(
        name="systemd",
        status="BROKE",
        message=f"{len(services)} failed services detected",
        details=services,
        remediation="Run: systemctl status <service> && journalctl -u <service>"
    )
