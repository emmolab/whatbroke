import os
import socket
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def check():
    route = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True,
        text=True
    )

    if not route.stdout.strip():
        return Result(
            name="networking",
            status="BROKE",
            message="No default network route"
        )

    try:
        socket.gethostbyname("google.com")
    except socket.gaierror:
        return Result(
            name="networking",
            status="BROKE",
            message="DNS resolution failed"
        )

    return Result(
        name="networking",
        status="OK",
        message="Networking looks healthy"
    )
