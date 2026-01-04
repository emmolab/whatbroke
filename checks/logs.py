import os
import os
import subprocess
import sys
import re

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _check_systemd_logs():
    """Check systemd journal for errors"""
    critical_entries = []
    error_entries = []
    
    try:
        # Check critical priority logs
        proc = subprocess.run(
            ["journalctl", "-p", "0..2", "--no-pager", "--output=short"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            for line in lines[-50:]:  # Last 50 entries
                if "crit" in line.lower() or "alert" in line.lower() or "emerg" in line.lower():
                    critical_entries.append(line)
                elif "err" in line.lower() or "error" in line.lower():
                    error_entries.append(line)
        
        # Check last 24 hours
        proc = subprocess.run(
            ["journalctl", "-p", "0..3", "--since", "24 hours ago", "--no-pager", "--output=short"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            recent_issues = []
            for line in lines:
                if any(keyword in line.lower() for keyword in ["error", "failed", "critical", "panic", "oops"]):
                    recent_issues.append(line)
    
    except Exception:
        pass
    
    try:
        # Check last 24 hours
        proc = subprocess.run(
            ["journalctl", "-p", "0..3", "--since", "24 hours ago", "--no-pager", "--output=short"],
            capture_output=True,
            text=True
        )
        
        recent_issues = []
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            for line in lines:
                if any(keyword in line.lower() for keyword in ["error", "failed", "critical", "panic", "oops"]):
                    recent_issues.append(line)
    except Exception:
        recent_issues = []
    
    return critical_entries, error_entries, recent_issues

def _check_kernel_messages():
    """Check kernel messages for errors"""
    kernel_issues = []
    
    try:
        # Check dmesg for errors and warnings
        proc = subprocess.run(
            ["dmesg", "--level", "err,warn,crit,alert,emerg"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            # Filter to last 100 lines to avoid overwhelming output
            kernel_issues = [line for line in lines[-100:] if line.strip()]
    
    except Exception:
        pass
    
    return kernel_issues

def _check_application_logs():
    """Check common application logs for errors"""
    app_log_errors = []
    log_paths = [
        ("/var/log/nginx/error.log", "Nginx"),
        ("/var/log/apache2/error.log", "Apache"),
        ("/var/log/mysql/error.log", "MySQL"),
        ("/var/log/mariadb/mariadb.log", "MariaDB"),
        ("/var/log/postgresql/postgresql.log", "PostgreSQL"),
        ("/var/log/redis/redis-server.log", "Redis"),
    ]
    
    for log_path, app_name in log_paths:
        if os.path.exists(log_path):
            try:
                # Get last 20 lines of log file
                proc = subprocess.run(
                    ["tail", "-n", "20", log_path],
                    capture_output=True,
                    text=True
                )
                
                if proc.returncode == 0:
                    lines = proc.stdout.strip().splitlines()
                    error_count = 0
                    for line in lines:
                        if any(keyword in line.lower() for keyword in ["error", "fatal", "critical", "panic"]):
                            error_count += 1
                            app_log_errors.append(f"{app_name}: {line.strip()[:200]}")  # Limit length
                    
                    if error_count > 0:
                        app_log_errors.insert(0, f"{app_name}: {error_count} errors in last 20 lines")
            
            except Exception:
                continue
    
    return app_log_errors

def _check_log_file_sizes():
    """Check for unusually large log files"""
    large_logs = []
    
    try:
        log_dirs = ["/var/log", "/var/log/audit"]
        
        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                proc = subprocess.run(
                    ["find", log_dir, "-name", "*.log", "-size", "+1G", "-exec", "ls", "-lh", "{}", ";"],
                    capture_output=True,
                    text=True
                )
                
                if proc.returncode == 0 and proc.stdout.strip():
                    large_logs.extend([f"Large log: {line}" for line in proc.stdout.strip().splitlines()])
    
    except Exception:
        pass
    
    return large_logs

def check():
    """Comprehensive log monitoring check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Systemd logs check
    critical_entries, error_entries, recent_issues = _check_systemd_logs()
    
    if critical_entries:
        details.append(f"Systemd CRITICAL entries: {len(critical_entries)}")
        details.extend(critical_entries[:5])  # Show first 5
        worst_status = "CRIT"
        remediation = "Check critical systemd logs: journalctl -p crit -xb"
    elif error_entries:
        details.append(f"Systemd ERROR entries: {len(error_entries)}")
        details.extend(error_entries[:3])  # Show first 3
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check systemd errors: journalctl -p err -xb"
    else:
        details.append("Systemd logs: OK")
    
    if recent_issues:
        details.append(f"Recent issues (24h): {len(recent_issues)}")
        details.extend(recent_issues[:3])
        if worst_status == "OK":
            worst_status = "WARN"
    
    # Kernel messages check
    kernel_issues = _check_kernel_messages()
    if kernel_issues:
        details.append(f"Kernel issues: {len(kernel_issues)}")
        details.extend(kernel_issues[:5])
        if worst_status == "OK" or (worst_status == "WARN" and any("crit" in issue.lower() or "panic" in issue.lower() for issue in kernel_issues)):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check kernel messages: dmesg | grep -i error"
    else:
        details.append("Kernel messages: OK")
    
    # Application logs check
    app_log_errors = _check_application_logs()
    if app_log_errors:
        details.extend(app_log_errors[:10])  # Limit to first 10
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check application logs: /var/log/*/*.log"
    else:
        details.append("Application logs: OK")
    
    # Log file sizes check
    large_logs = _check_log_file_sizes()
    if large_logs:
        details.extend(large_logs)
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Rotate large log files: logrotate -f /etc/logrotate.conf"
    else:
        details.append("Log file sizes: OK")
    
    # Main message
    message_parts = []
    message_parts.append(f"Systemd errors: {len(error_entries)}")
    message_parts.append(f"Critical entries: {len(critical_entries)}")
    message_parts.append(f"Kernel issues: {len(kernel_issues)}")
    message_parts.append(f"App errors: {len(app_log_errors)}")
    message_parts.append(f"Large logs: {len(large_logs)}")
    
    main_message = ", ".join(message_parts)
    
    if worst_status == "OK":
        main_message = "All log checks passed - No issues found"
    
    return Result(
        name="logs",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
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
