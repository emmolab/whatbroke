import os
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def check():
    info = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True
    )

    if info.returncode != 0:
        return Result(
            name="docker",
            status="WARN",
            message="Docker not running or not installed"
        )

    exited = subprocess.run(
        ["docker", "ps", "-a", "--filter", "status=exited", "-q"],
        capture_output=True,
        text=True
    )

    containers = exited.stdout.strip().splitlines()
    if containers:
        return Result(
            name="docker",
            status="WARN",
            message=f"{len(containers)} exited containers",
            details=containers,
        )

    return Result(
        name="docker",
        status="OK",
        message="Docker healthy"
    )
