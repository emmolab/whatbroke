import os
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

TOP_N = 5  # number of processes to show

def _top_cpu_processes():
    proc = subprocess.run(
        ["ps", "-eo", "pid,user,%cpu,comm", "--sort=-%cpu"],
        capture_output=True,
        text=True
    )

    lines = proc.stdout.strip().splitlines()[1:TOP_N + 1]
    return [line.strip() for line in lines]

def _top_mem_processes():
    proc = subprocess.run(
        ["ps", "-eo", "pid,user,%mem,comm", "--sort=-%mem"],
        capture_output=True,
        text=True
    )

    lines = proc.stdout.strip().splitlines()[1:TOP_N + 1]
    return [line.strip() for line in lines]

def check():
    # Load averages
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    load_ratio = load1 / cpu_count

    # Memory info
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key.strip()] = int(value.strip().split()[0])

    mem_total = meminfo.get("MemTotal", 1)
    mem_available = meminfo.get("MemAvailable", 0)
    mem_available_pct = mem_available / mem_total * 100

    details = []
    remediation = None

    # Determine status
    if load_ratio > 2 or mem_available_pct < 5:
        status = "BROKE"
    elif load_ratio > 1 or mem_available_pct < 15:
        status = "WARN"
    else:
        status = "OK"

    # Collect offenders
    if load_ratio > 1:
        details.append("Top CPU-consuming processes:")
        details.extend(_top_cpu_processes())
        remediation = "Investigate or restart high-CPU processes (top, htop, systemctl)"

    if mem_available_pct < 15:
        details.append("Top memory-consuming processes:")
        details.extend(_top_mem_processes())
        remediation = "Investigate memory leaks or restart high-memory processes"

    message = (
        f"Load: {load1:.2f} ({cpu_count} CPUs), "
        f"Memory available: {mem_available_pct:.1f}%"
    )

    return Result(
        name="hardware",
        status=status,
        message=message,
        details=details,
        remediation=remediation,
    )
