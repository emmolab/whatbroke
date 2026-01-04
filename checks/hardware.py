import os
import shutil
import subprocess
import sys
import re

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

TOP_N = 5  # number of processes to show

def _top_cpu_processes():
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,user,%cpu,comm", "--sort=-%cpu"],
            capture_output=True,
            text=True
        )
        lines = proc.stdout.strip().splitlines()[1:TOP_N + 1]
        return [line.strip() for line in lines]
    except Exception:
        return []

def _top_mem_processes():
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,user,%mem,comm", "--sort=-%mem"],
            capture_output=True,
            text=True
        )
        lines = proc.stdout.strip().splitlines()[1:TOP_N + 1]
        return [line.strip() for line in lines]
    except Exception:
        return []

def _get_swap_usage():
    """Get swap usage information"""
    try:
        proc = subprocess.run(
            ["free", "-h"],
            capture_output=True,
            text=True
        )
        lines = proc.stdout.strip().splitlines()
        swap_line = next((line for line in lines if line.startswith("Swap:")), None)
        
        if swap_line:
            parts = swap_line.split()
            if len(parts) >= 3:
                total = parts[1]
                used = parts[2]
                free = parts[3]
                
                # Calculate percentage
                if total != '0B' and 'B' in total:
                    total_bytes = float(total.replace('B', ''))
                    used_bytes = float(used.replace('B', ''))
                    percent_used = (used_bytes / total_bytes) * 100
                    return percent_used, used, total
        return 0, "0B", "0B"
    except Exception:
        return 0, "0B", "0B"

def _get_temperature_sensors():
    """Get system temperature readings"""
    temps = []
    
    try:
        # Check /sys/class/thermal for thermal zones
        thermal_zones = [d for d in os.listdir('/sys/class/thermal') if d.startswith('thermal_zone')]
        
        for zone in thermal_zones:
            try:
                temp_file = f"/sys/class/thermal/{zone}/temp"
                with open(temp_file, 'r') as f:
                    temp_c = int(f.read().strip()) / 1000  # Convert from millidegrees
                    
                    # Only report temperatures that seem reasonable
                    if 0 < temp_c < 150:
                        temps.append({
                            'sensor': zone,
                            'temp_c': temp_c,
                            'location': 'thermal_zone'
                        })
            except (IOError, ValueError):
                continue
        
        # Check for lm_sensors
        if shutil.which('sensors'):
            proc = subprocess.run(
                ["sensors"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if proc.returncode == 0:
                # Parse lm_sensors output
                lines = proc.stdout.splitlines()
                for line in lines:
                    # Look for temperature lines
                    temp_match = re.search(r'([^:]+):\s+([+-]?\d+\.?\d*)°C', line)
                    if temp_match:
                        sensor_name = temp_match.group(1).strip()
                        temp_c = float(temp_match.group(2))
                        
                        if 0 < temp_c < 150:
                            temps.append({
                                'sensor': sensor_name,
                                'temp_c': temp_c,
                                'location': 'sensors'
                            })
    
    except Exception:
        pass
    
    return temps

def _get_battery_status():
    """Check battery/UPS status"""
    battery_info = []
    
    try:
        # Check for batteries
        power_supply_dir = '/sys/class/power_supply'
        if os.path.exists(power_supply_dir):
            for device in os.listdir(power_supply_dir):
                device_path = os.path.join(power_supply_dir, device)
                
                # Check if it's a battery
                if os.path.exists(os.path.join(device_path, 'capacity')):
                    try:
                        capacity = int(open(os.path.join(device_path, 'capacity')).read().strip())
                        status = open(os.path.join(device_path, 'status')).read().strip() if os.path.exists(os.path.join(device_path, 'status')) else 'Unknown'
                        
                        battery_info.append({
                            'device': device,
                            'capacity': capacity,
                            'status': status
                        })
                        
                        # Check health if available
                        if os.path.exists(os.path.join(device_path, 'health')):
                            health = open(os.path.join(device_path, 'health')).read().strip()
                            battery_info[-1]['health'] = health
                    except (IOError, ValueError):
                        continue
    
    except Exception:
        pass
    
    return battery_info

def check():
    """Comprehensive hardware and performance check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # CPU Load check
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    load_ratio = load1 / cpu_count
    
    if load_ratio > 0.9:
        load_status = "CRIT"
        details.append(f"CPU load {load1:.2f} - CRITICAL ({cpu_count} cores, {load_ratio*100:.1f}% per core)")
        if worst_status == "OK":
            worst_status = load_status
    elif load_ratio > 0.7:
        load_status = "WARN"
        details.append(f"CPU load {load1:.2f} - WARNING ({cpu_count} cores, {load_ratio*100:.1f}% per core)")
        if worst_status == "OK":
            worst_status = load_status
    else:
        load_status = "OK"
        details.append(f"CPU load {load1:.2f} ({cpu_count} cores)")
    
    # Memory check
    mem_status = "OK"
    mem_available_pct = 100  # Default value
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                key, value = line.split(":", 1)
                meminfo[key.strip()] = int(value.strip().split()[0])

        mem_total = meminfo.get("MemTotal", 1)
        mem_available = meminfo.get("MemAvailable", 0)
        mem_available_pct = (mem_available / mem_total) * 100

        if mem_available_pct < 10:
            mem_status = "CRIT"
            details.append(f"Memory available {mem_available_pct:.1f}% - CRITICAL")
            if worst_status == "OK" or (worst_status == "WARN" and mem_status == "CRIT"):
                worst_status = mem_status
        elif mem_available_pct < 20:
            mem_status = "WARN"
            details.append(f"Memory available {mem_available_pct:.1f}% - WARNING")
            if worst_status == "OK":
                worst_status = mem_status
        else:
            details.append(f"Memory available {mem_available_pct:.1f}%")
    
    except Exception:
        mem_status = "OK"
        details.append("Memory status: Unable to check")
    
    # Swap check
    swap_pct, swap_used, swap_total = _get_swap_usage()
    if swap_pct > 80:
        swap_status = "CRIT"
        details.append(f"Swap usage {swap_used}/{swap_total} ({swap_pct:.1f}%) - CRITICAL")
        if worst_status == "OK" or (worst_status == "WARN" and swap_status == "CRIT"):
            worst_status = swap_status
    elif swap_pct > 50:
        swap_status = "WARN"
        details.append(f"Swap usage {swap_used}/{swap_total} ({swap_pct:.1f}%) - WARNING")
        if worst_status == "OK":
            worst_status = swap_status
    elif swap_pct > 0:
        swap_status = "OK"
        details.append(f"Swap usage {swap_used}/{swap_total} ({swap_pct:.1f}%)")
    
    # Temperature check
    temps = _get_temperature_sensors()
    high_temp_issues = []
    crit_temp_issues = []
    
    for temp in temps:
        temp_c = temp['temp_c']
        sensor = temp['sensor']
        
        if temp_c > 85:
            crit_temp_issues.append(f"{sensor}: {temp_c:.1f}°C - CRITICAL")
        elif temp_c > 70:
            high_temp_issues.append(f"{sensor}: {temp_c:.1f}°C - WARNING")
    
    if crit_temp_issues:
        details.extend(crit_temp_issues)
        if worst_status == "OK":
            worst_status = "CRIT"
    elif high_temp_issues:
        details.extend(high_temp_issues)
        if worst_status == "OK":
            worst_status = "WARN"
    elif temps:
        max_temp = max(t['temp_c'] for t in temps)
        details.append(f"Temperatures OK (max: {max_temp:.1f}°C)")
    
    # Battery/UPS check
    batteries = _get_battery_status()
    battery_issues = []
    
    for battery in batteries:
        capacity = battery.get('capacity', 100)
        status = battery.get('status', 'Unknown')
        device = battery.get('device', 'Unknown')
        health = battery.get('health', 'Unknown')
        
        if capacity < 10:
            battery_issues.append(f"{device}: {capacity}% battery - CRITICAL")
            if worst_status == "OK":
                worst_status = "CRIT"
        elif capacity < 20:
            battery_issues.append(f"{device}: {capacity}% battery - WARNING")
            if worst_status == "OK":
                worst_status = "WARN"
        
        if health == 'Bad' or health == 'Poor':
            battery_issues.append(f"{device}: Battery health {health} - CRITICAL")
            if worst_status == "OK":
                worst_status = "CRIT"
    
    if battery_issues:
        details.extend(battery_issues)
    elif batteries:
        details.append(f"Batteries OK ({len(batteries)} devices)")
    
    # Add top processes if resources are constrained
    if load_ratio > 0.7 or mem_available_pct < 20:
        if load_ratio > 0.7:
            details.append("Top CPU-consuming processes:")
            details.extend(_top_cpu_processes())
        
        if mem_available_pct < 20:
            details.append("Top memory-consuming processes:")
            details.extend(_top_mem_processes())
        
        remediation = "Investigate resource usage: top, htop, systemctl, check for runaway processes"
    
    # Main message
    message_parts = []
    message_parts.append(f"Load: {load1:.2f} ({cpu_count} CPUs)")
    message_parts.append(f"Memory: {mem_available_pct:.1f}% available")
    if swap_pct > 0:
        message_parts.append(f"Swap: {swap_pct:.1f}% used")
    if temps:
        max_temp = max(t['temp_c'] for t in temps)
        message_parts.append(f"Max temp: {max_temp:.1f}°C")
    
    main_message = ", ".join(message_parts)
    
    return Result(
        name="hardware",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )
