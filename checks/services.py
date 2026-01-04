import os
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _check_systemd_failed_services():
    """Check for failed systemd services"""
    failed_services = []
    
    try:
        proc = subprocess.run(
            ["systemctl", "--failed", "--no-legend"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            output = proc.stdout.strip()
            if output:
                for line in output.splitlines():
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 1:
                            service_name = parts[0]
                            failed_services.append(service_name)
    except Exception:
        pass
    
    return failed_services

def _check_zombie_processes():
    """Check for zombie processes"""
    zombie_count = 0
    zombie_details = []
    
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,stat,comm"],
            capture_output=True,
            text=True
        )
        
        lines = proc.stdout.strip().splitlines()
        for line in lines[1:]:  # Skip header
            if 'Z' in line.split()[1]:  # Z state indicates zombie
                zombie_count += 1
                parts = line.split()
                if len(parts) >= 3:
                    pid = parts[0]
                    comm = parts[2]
                    zombie_details.append(f"PID {pid}: {comm}")
    except Exception:
        pass
    
    return zombie_count, zombie_details

def _check_high_resource_processes():
    """Check processes with high CPU or memory usage"""
    high_cpu = []
    high_mem = []
    
    try:
        # High CPU processes (>50%)
        proc = subprocess.run(
            ["ps", "-eo", "pid,user,%cpu,comm", "--sort=-%cpu"],
            capture_output=True,
            text=True
        )
        
        lines = proc.stdout.strip().splitlines()
        for line in lines[1:6]:  # Top 5
            if line.strip():
                parts = line.split()
                if len(parts) >= 3 and float(parts[2]) > 50:
                    high_cpu.append(f"PID {parts[0]} ({parts[1]}): {parts[2]}% CPU - {parts[3]}")
        
        # High memory processes (>20%)
        proc = subprocess.run(
            ["ps", "-eo", "pid,user,%mem,comm", "--sort=-%mem"],
            capture_output=True,
            text=True
        )
        
        lines = proc.stdout.strip().splitlines()
        for line in lines[1:6]:  # Top 5
            if line.strip():
                parts = line.split()
                if len(parts) >= 3 and float(parts[2]) > 20:
                    high_mem.append(f"PID {parts[0]} ({parts[1]}): {parts[2]}% Memory - {parts[3]}")
                    
    except Exception:
        pass
    
    return high_cpu, high_mem

def _check_critical_services():
    """Check status of critical services"""
    critical_services = []
    service_checks = [
        ("nginx", "web server"),
        ("apache2", "web server"),
        ("mysql", "database"),
        ("mariadb", "database"),
        ("postgresql", "database"),
        ("redis", "cache"),
        ("docker", "container runtime"),
        ("ssh", "remote access"),
        ("sshd", "remote access"),
    ]
    
    for service, description in service_checks:
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True
            )
            
            if "active" not in proc.stdout.strip():
                critical_services.append(f"{service} ({description}): {proc.stdout.strip()}")
        except Exception:
            pass
    
    return critical_services

def _check_port_conflicts():
    """Check for port conflicts"""
    port_conflicts = []
    
    try:
        # Get all listening ports
        proc = subprocess.run(
            ["netstat", "-tuln"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            ports = {}
            lines = proc.stdout.strip().splitlines()
            
            for line in lines[2:]:  # Skip headers
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 4:
                        proto = parts[0]
                        local_address = parts[3]
                        
                        # Extract port number
                        if ':' in local_address:
                            port = local_address.split(':')[-1]
                        else:
                            port = local_address
                        
                        # Common service ports to check for conflicts
                        common_ports = ['22', '80', '443', '3306', '5432', '6379', '25', '53', '8080']
                        if port in common_ports:
                            if port not in ports:
                                ports[port] = []
                            ports[port].append(f"{proto}/{local_address}")
            
            # Find duplicates
            for port, listeners in ports.items():
                if len(listeners) > 1:
                    port_conflicts.append(f"Port {port}: Multiple services ({', '.join(listeners)})")
    
    except Exception:
        pass
    
    return port_conflicts

def check():
    """Comprehensive system services and processes check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Check systemd failed services
    failed_services = _check_systemd_failed_services()
    if failed_services:
        details.extend([f"Failed service: {service}" for service in failed_services])
        worst_status = "CRIT"
        remediation = "Check failed services: systemctl status <service> && journalctl -u <service>"
    
    # Check zombie processes
    zombie_count, zombie_details = _check_zombie_processes()
    if zombie_count > 0:
        details.append(f"Found {zombie_count} zombie processes")
        details.extend(zombie_details[:5])  # Show first 5
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Kill zombie processes: kill -9 <pid> or reboot if persistent"
    
    # Check high resource processes
    high_cpu, high_mem = _check_high_resource_processes()
    if high_cpu or high_mem:
        if high_cpu:
            details.append("High CPU processes:")
            details.extend(high_cpu)
        if high_mem:
            details.append("High memory processes:")
            details.extend(high_mem)
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Investigate high-resource processes: top, htop, kill if necessary"
    
    # Check critical services
    critical_services = _check_critical_services()
    if critical_services:
        details.extend(critical_services)
        if worst_status == "OK":
            worst_status = "CRIT"
        if not remediation:
            remediation = "Start critical services: systemctl start <service>"
    
    # Check port conflicts
    port_conflicts = _check_port_conflicts()
    if port_conflicts:
        details.extend(port_conflicts)
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Resolve port conflicts: stop conflicting services or change ports"
    
    # Main message
    message_parts = []
    message_parts.append(f"Failed services: {len(failed_services)}")
    message_parts.append(f"Zombie processes: {zombie_count}")
    message_parts.append(f"High CPU processes: {len(high_cpu)}")
    message_parts.append(f"High memory processes: {len(high_mem)}")
    message_parts.append(f"Critical services down: {len(critical_services)}")
    message_parts.append(f"Port conflicts: {len(port_conflicts)}")
    
    main_message = ", ".join(message_parts)
    
    if worst_status == "OK":
        main_message = "All system services and processes healthy"
    
    return Result(
        name="services",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )