import os
import re
import shutil
import subprocess

from ..result import Result, escalate

TOP_N = 5


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _read_meminfo() -> dict:
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split(":", 1)
            if len(parts) == 2:
                info[parts[0].strip()] = int(parts[1].strip().split()[0])
    return info  # values in kB


def _get_swap_usage():
    """Return (percent_used, used_human, total_human) from /proc/meminfo."""
    try:
        m = _read_meminfo()
        total_kb = m.get("SwapTotal", 0)
        free_kb  = m.get("SwapFree",  0)
        used_kb  = total_kb - free_kb
        if total_kb == 0:
            return 0.0, "0 kB", "0 kB"
        pct = (used_kb / total_kb) * 100
        def _fmt(kb):
            if kb >= 1024 * 1024:
                return f"{kb / 1024 / 1024:.1f} GB"
            if kb >= 1024:
                return f"{kb / 1024:.1f} MB"
            return f"{kb} kB"
        return pct, _fmt(used_kb), _fmt(total_kb)
    except Exception:
        return 0.0, "0 kB", "0 kB"


def _get_uptime() -> str:
    """Return human-readable uptime string."""
    try:
        with open("/proc/uptime") as f:
            total_seconds = float(f.read().split()[0])
        days    = int(total_seconds // 86400)
        hours   = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)
        if days:
            return f"{days}d {hours}h {minutes}m"
        return f"{hours}h {minutes}m"
    except Exception:
        return "unknown"


def _get_temperatures():
    """Return list of (sensor_name, temp_c) tuples."""
    temps = []
    # /sys/class/thermal
    try:
        thermal_dir = '/sys/class/thermal'
        for zone in sorted(os.listdir(thermal_dir)):
            if not zone.startswith('thermal_zone'):
                continue
            try:
                with open(f"{thermal_dir}/{zone}/temp") as f:
                    temp_c = int(f.read().strip()) / 1000
                if 0 < temp_c < 150:
                    temps.append((zone, temp_c))
            except (IOError, ValueError):
                pass
    except Exception:
        pass

    # lm_sensors
    if shutil.which('sensors'):
        try:
            proc = _run(["sensors"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    m = re.search(r'([^:]+):\s+[+-]?(\d+\.?\d*)°C', line)
                    if m:
                        name   = m.group(1).strip()
                        temp_c = float(m.group(2))
                        if 0 < temp_c < 150:
                            temps.append((name, temp_c))
        except Exception:
            pass
    return temps


def _get_batteries():
    """Return list of dicts for each battery/UPS device."""
    batteries = []
    psu_dir = '/sys/class/power_supply'
    if not os.path.exists(psu_dir):
        return batteries
    try:
        for device in os.listdir(psu_dir):
            dev_path = os.path.join(psu_dir, device)
            cap_file = os.path.join(dev_path, 'capacity')
            if not os.path.exists(cap_file):
                continue
            try:
                capacity = int(open(cap_file).read().strip())
                status_f = os.path.join(dev_path, 'status')
                status   = open(status_f).read().strip() if os.path.exists(status_f) else 'Unknown'
                health_f = os.path.join(dev_path, 'health')
                health   = open(health_f).read().strip() if os.path.exists(health_f) else None
                batteries.append({'device': device, 'capacity': capacity,
                                   'status': status, 'health': health})
            except (IOError, ValueError):
                pass
    except Exception:
        pass
    return batteries


def _top_processes(sort_key: str) -> list:
    """Return top-N process lines sorted by %cpu or %mem."""
    try:
        proc = _run(
            ["ps", "-eo", f"pid,user,{sort_key},comm", f"--sort=-{sort_key}"],
            timeout=10,
        )
        return [l.strip() for l in proc.stdout.strip().splitlines()[1:TOP_N + 1]]
    except Exception:
        return []


def check() -> Result:
    """CPU load, memory, swap, temperatures, battery, uptime."""
    details = []
    status  = "OK"
    remediation = None

    # Uptime (always shown)
    uptime = _get_uptime()
    details.append(f"Uptime: {uptime}")
    try:
        with open("/proc/uptime") as f:
            uptime_days = float(f.read().split()[0]) / 86400
        if uptime_days > 365:
            details.append("WARNING: System uptime > 1 year — kernel update likely needed")
            status = escalate(status, "WARN")
    except Exception:
        pass

    # CPU load
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    load_ratio = load1 / cpu_count

    if load_ratio >= 0.9:
        details.append(
            f"CPU load {load1:.2f} ({cpu_count} cores) — CRITICAL ({load_ratio*100:.0f}% per core)")
        status = escalate(status, "CRIT")
    elif load_ratio >= 0.7:
        details.append(
            f"CPU load {load1:.2f} ({cpu_count} cores) — WARNING ({load_ratio*100:.0f}% per core)")
        status = escalate(status, "WARN")
    else:
        details.append(
            f"CPU load {load1:.2f} (1m) / {load5:.2f} (5m) / {load15:.2f} (15m) — {cpu_count} cores")

    # Memory
    mem_pct = 100.0
    try:
        m = _read_meminfo()
        total  = m.get("MemTotal",     1)
        avail  = m.get("MemAvailable", 0)
        mem_pct = (avail / total) * 100

        total_gb = total / 1024 / 1024
        avail_gb = avail / 1024 / 1024

        if mem_pct < 10:
            details.append(
                f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB) — CRITICAL")
            status = escalate(status, "CRIT")
        elif mem_pct < 20:
            details.append(
                f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB) — WARNING")
            status = escalate(status, "WARN")
        else:
            details.append(
                f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB)")
    except Exception:
        details.append("Memory: unable to read /proc/meminfo")

    # Swap
    swap_pct, swap_used, swap_total = _get_swap_usage()
    if swap_pct > 80:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%) — CRITICAL")
        status = escalate(status, "CRIT")
    elif swap_pct > 50:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%) — WARNING")
        status = escalate(status, "WARN")
    elif swap_pct > 0:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%)")
    else:
        details.append("Swap: not in use")

    # Temperatures
    temps = _get_temperatures()
    crit_temps = [(n, t) for n, t in temps if t > 85]
    warn_temps = [(n, t) for n, t in temps if 70 < t <= 85]

    if crit_temps:
        for name, t in crit_temps:
            details.append(f"Temperature {name}: {t:.1f}°C — CRITICAL")
        status = escalate(status, "CRIT")
        remediation = "Check cooling; shut down non-essential workloads"
    elif warn_temps:
        for name, t in warn_temps:
            details.append(f"Temperature {name}: {t:.1f}°C — WARNING")
        status = escalate(status, "WARN")
    elif temps:
        max_t = max(t for _, t in temps)
        details.append(f"Temperatures OK (max {max_t:.1f}°C)")

    # Battery / UPS
    for bat in _get_batteries():
        cap    = bat['capacity']
        dev    = bat['device']
        health = bat.get('health')

        if cap < 10:
            details.append(f"Battery {dev}: {cap}% — CRITICAL (very low)")
            status = escalate(status, "CRIT")
        elif cap < 20:
            details.append(f"Battery {dev}: {cap}% — WARNING")
            status = escalate(status, "WARN")
        else:
            details.append(f"Battery {dev}: {cap}% ({bat['status']})")

        if health and health.lower() in ('bad', 'poor', 'dead'):
            details.append(f"Battery {dev} health: {health} — CRITICAL")
            status = escalate(status, "CRIT")

    # Top processes when resources are constrained
    if load_ratio >= 0.7:
        details.append("Top CPU consumers:")
        details.extend(_top_processes('%cpu'))
        remediation = remediation or "Investigate high-load processes: top, htop"

    if mem_pct < 20:
        details.append("Top memory consumers:")
        details.extend(_top_processes('%mem'))
        remediation = remediation or "Investigate memory usage: free -h, ps aux --sort=-%mem"

    # Summary message
    msg_parts = [
        f"Load {load1:.2f}/{cpu_count}",
        f"Mem {mem_pct:.0f}% free",
    ]
    if swap_pct > 0:
        msg_parts.append(f"Swap {swap_pct:.0f}%")
    if temps:
        msg_parts.append(f"Temp {max(t for _, t in temps):.0f}°C")
    msg_parts.append(f"Up {uptime}")

    if status == "OK":
        return Result(
            name="hardware",
            status="OK",
            message="Hardware healthy — " + ", ".join(msg_parts),
            details=details,
        )
    return Result(
        name="hardware",
        status=status,
        message=", ".join(msg_parts),
        details=details,
        remediation=remediation,
    )
