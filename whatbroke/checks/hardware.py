import os
import re
import shutil
import subprocess

from ..result import Result, escalate

TOP_N = 5
_LONG_UPTIME_NOTE_DAYS = 365
_MEMORY_PRESSURE_WARN_SOME_AVG10 = 1.0
_MEMORY_PRESSURE_BROKE_SOME_AVG10 = 5.0
_MEMORY_PRESSURE_WARN_FULL_AVG10 = 0.1
_MEMORY_PRESSURE_BROKE_FULL_AVG10 = 1.0


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _read_meminfo() -> dict:
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split(":", 1)
            if len(parts) == 2:
                info[parts[0].strip()] = int(parts[1].strip().split()[0])
    return info


def _get_swap_usage():
    try:
        m = _read_meminfo()
        total_kb = m.get("SwapTotal", 0)
        free_kb = m.get("SwapFree", 0)
        used_kb = total_kb - free_kb
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


def _get_uptime() -> tuple[str, float | None]:
    try:
        with open("/proc/uptime") as f:
            total_seconds = float(f.read().split()[0])
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)
        if days:
            return f"{days}d {hours}h {minutes}m", total_seconds / 86400
        return f"{hours}h {minutes}m", total_seconds / 86400
    except Exception:
        return "unknown", None


def _get_temperatures():
    temps = []
    try:
        thermal_dir = "/sys/class/thermal"
        for zone in sorted(os.listdir(thermal_dir)):
            if not zone.startswith("thermal_zone"):
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

    if shutil.which("sensors"):
        try:
            proc = _run(["sensors"], timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    m = re.search(r"([^:]+):\s+[+-]?(\d+\.?\d*)°C", line)
                    if m:
                        name = m.group(1).strip()
                        temp_c = float(m.group(2))
                        if 0 < temp_c < 150:
                            temps.append((name, temp_c))
        except Exception:
            pass
    return temps


def _top_processes(sort_key: str) -> list:
    try:
        proc = _run(["ps", "-eo", f"pid,user,{sort_key},comm", f"--sort=-{sort_key}"], timeout=10)
        return [l.strip() for l in proc.stdout.strip().splitlines()[1 : TOP_N + 1]]
    except Exception:
        return []


def _read_pressure(resource: str) -> dict[str, dict[str, float]]:
    pressure = {}
    try:
        with open(f"/proc/pressure/{resource}") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split()
                category = parts[0]
                metrics = {}
                for field in parts[1:]:
                    if "=" not in field:
                        continue
                    key, value = field.split("=", 1)
                    try:
                        metrics[key] = float(value)
                    except ValueError:
                        continue
                if metrics:
                    pressure[category] = metrics
    except Exception:
        pass
    return pressure


def check() -> Result:
    """CPU load, memory, swap, temperatures, uptime."""
    details = []
    status = "OK"
    remediation = None
    memory_pressure_triggered = False

    uptime, uptime_days = _get_uptime()
    details.append(f"Uptime: {uptime}")
    if uptime_days is not None and uptime_days > _LONG_UPTIME_NOTE_DAYS:
        details.append("Uptime note: long-running host; confirm kernel/userspace patch cadence is intentional")

    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    load_ratio = load1 / cpu_count

    if load_ratio >= 1.5:
        details.append(f"CPU load {load1:.2f} on {cpu_count} cores — sustained saturation")
        status = escalate(status, "CRIT")
    elif load_ratio >= 1.0:
        details.append(f"CPU load {load1:.2f} on {cpu_count} cores — fully loaded")
        status = escalate(status, "WARN")
    else:
        details.append(f"CPU load {load1:.2f} (1m) / {load5:.2f} (5m) / {load15:.2f} (15m) across {cpu_count} cores")

    mem_pct = 100.0
    try:
        m = _read_meminfo()
        total = m.get("MemTotal", 1)
        avail = m.get("MemAvailable", 0)
        mem_pct = (avail / total) * 100
        total_gb = total / 1024 / 1024
        avail_gb = avail / 1024 / 1024

        if mem_pct < 5:
            details.append(f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB)")
            status = escalate(status, "CRIT")
        elif mem_pct < 10:
            details.append(f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB)")
            status = escalate(status, "WARN")
        else:
            details.append(f"Memory available {mem_pct:.1f}% ({avail_gb:.1f} GB / {total_gb:.1f} GB)")
    except Exception:
        details.append("Memory: unable to read /proc/meminfo")

    swap_pct, swap_used, swap_total = _get_swap_usage()
    if swap_pct > 90:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%)")
        status = escalate(status, "CRIT")
    elif swap_pct > 70:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%)")
        status = escalate(status, "WARN")
    elif swap_pct > 0:
        details.append(f"Swap {swap_used}/{swap_total} ({swap_pct:.0f}%)")
    else:
        details.append("Swap: not in use")

    memory_pressure = _read_pressure("memory")
    pressure_some = memory_pressure.get("some", {})
    pressure_full = memory_pressure.get("full", {})
    some_avg10 = pressure_some.get("avg10", 0.0)
    full_avg10 = pressure_full.get("avg10", 0.0)

    if full_avg10 >= _MEMORY_PRESSURE_BROKE_FULL_AVG10:
        details.append(f"Memory pressure: full avg10 {full_avg10:.2f} — tasks are stalling in reclaim")
        status = escalate(status, "BROKE")
        remediation = remediation or "Investigate memory pressure with free -h, ps aux --sort=-%mem, and cgroup/container limits"
        memory_pressure_triggered = True
    elif some_avg10 >= _MEMORY_PRESSURE_BROKE_SOME_AVG10 and (mem_pct < 20 or swap_pct > 20):
        details.append(f"Memory pressure: some avg10 {some_avg10:.2f} with low headroom")
        status = escalate(status, "BROKE")
        remediation = remediation or "Investigate memory pressure with free -h, ps aux --sort=-%mem, and cgroup/container limits"
        memory_pressure_triggered = True
    elif full_avg10 >= _MEMORY_PRESSURE_WARN_FULL_AVG10 or (
        some_avg10 >= _MEMORY_PRESSURE_WARN_SOME_AVG10 and (mem_pct < 20 or swap_pct > 0)
    ):
        pressure_bits = []
        if some_avg10 >= _MEMORY_PRESSURE_WARN_SOME_AVG10:
            pressure_bits.append(f"some avg10 {some_avg10:.2f}")
        if full_avg10 >= _MEMORY_PRESSURE_WARN_FULL_AVG10:
            pressure_bits.append(f"full avg10 {full_avg10:.2f}")
        details.append("Memory pressure: " + ", ".join(pressure_bits))
        status = escalate(status, "WARN")
        remediation = remediation or "Investigate memory pressure with free -h, ps aux --sort=-%mem, and cgroup/container limits"
        memory_pressure_triggered = True
    elif some_avg10 > 0 or full_avg10 > 0:
        details.append(f"Memory pressure context: some avg10 {some_avg10:.2f}, full avg10 {full_avg10:.2f}")

    temps = _get_temperatures()
    crit_temps = [(n, t) for n, t in temps if t > 90]
    warn_temps = [(n, t) for n, t in temps if 80 < t <= 90]

    if crit_temps:
        for name, temp in crit_temps:
            details.append(f"Temperature {name}: {temp:.1f}°C")
        status = escalate(status, "CRIT")
        remediation = "Check cooling, airflow, and unusually hot workloads"
    elif warn_temps:
        for name, temp in warn_temps:
            details.append(f"Temperature {name}: {temp:.1f}°C")
        status = escalate(status, "WARN")
        remediation = remediation or "Check airflow and confirm the temperature is expected under current load"
    elif temps:
        details.append(f"Temperatures OK (max {max(t for _, t in temps):.1f}°C)")

    if load_ratio >= 1.0:
        details.append("Top CPU consumers:")
        details.extend(_top_processes("%cpu"))
        remediation = remediation or "Investigate high-load processes with top, htop, or systemd-cgtop"

    if mem_pct < 10 or memory_pressure_triggered:
        details.append("Top memory consumers:")
        details.extend(_top_processes("%mem"))
        remediation = remediation or "Investigate memory pressure with free -h and ps aux --sort=-%mem"

    msg_parts = [f"Load {load1:.2f}/{cpu_count}", f"Mem {mem_pct:.0f}% free"]
    if swap_pct > 0:
        msg_parts.append(f"Swap {swap_pct:.0f}%")
    if memory_pressure_triggered:
        msg_parts.append(f"MemPressure {some_avg10:.1f}/{full_avg10:.1f}")
    if temps:
        msg_parts.append(f"Temp {max(t for _, t in temps):.0f}°C")
    msg_parts.append(f"Up {uptime}")

    if status == "OK":
        return Result(name="hardware", status="OK", message="Hardware healthy — " + ", ".join(msg_parts), details=details)
    return Result(name="hardware", status=status, message=", ".join(msg_parts), details=details, remediation=remediation)
