import os
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _check_cron_jobs():
    """Check cron job execution status"""
    cron_issues = []
    
    try:
        # Check if any cron service is running
        cron_services = ["cron", "crond", "anacron"]
        cron_active = False
        
        for service in cron_services:
            proc = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True
            )
            if "active" in proc.stdout:
                cron_active = True
                break
        
        if not cron_active:
            cron_issues.append("Cron service: Not running")
            return cron_issues
        
        # Check for cron execution errors in logs
        log_files = ["/var/log/cron.log", "/var/log/cron", "/var/log/crond", "/var/log/syslog"]
        
        error_count = 0
        for log_file in log_files:
            if os.path.exists(log_file):
                # Get last 100 lines looking for execution errors
                proc = subprocess.run(
                    ["grep", "-i", "error\\|failed\\|permission denied", log_file, "|", "tail", "-n", "20"],
                    capture_output=True,
                    text=True,
                    shell=True
                )
                
                if proc.returncode == 0 and proc.stdout.strip():
                    error_count += len(proc.stdout.strip().splitlines())
                    cron_issues.extend([f"Cron error: {line.strip()[:100]}" for line in proc.stdout.strip().splitlines()[:3]])
        
        if error_count > 0:
            cron_issues.insert(0, f"Cron execution errors: {error_count} found")
    
    except Exception:
        cron_issues.append("Cron check: Unable to verify status")
    
    return cron_issues

def _check_systemd_timers():
    """Check systemd timer status"""
    timer_issues = []
    
    try:
        # List all timers
        proc = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            
            for line in lines[1:]:  # Skip header
                if not line.strip():
                    continue
                
                parts = line.split()
                if len(parts) >= 7:
                    timer_name = parts[0]
                    next_run = parts[2]
                    last_run = parts[3]
                    unit = parts[6]
                    
                    # Check for failed timers
                    if "failed" in last_run.lower() or "failed" in next_run.lower():
                        timer_issues.append(f"Timer {timer_name}: Failed")
                    # Check for inactive timers that should be running
                    elif "inactive" in unit.lower() and not timer_name.startswith("systemd-"):
                        timer_issues.append(f"Timer {timer_name}: Inactive")
    
    except Exception:
        timer_issues.append("Systemd timers: Unable to check status")
    
    return timer_issues

def _check_cron_syntax():
    """Check cron files for syntax errors"""
    cron_syntax_issues = []
    
    try:
        # Check /etc/crontab only if it exists and has content
        if os.path.exists("/etc/crontab"):
            with open("/etc/crontab", 'r') as f:
                content = f.read().strip()
            
            if content:  # Only check if not empty
                proc = subprocess.run(
                    ["bash", "-c", "cat /etc/crontab 2>/dev/null | crontab -l - 2>&1 1>/dev/null || echo 'Syntax error detected'"],
                    capture_output=True,
                    text=True
                )
                
                if proc.returncode != 0 or "syntax error" in proc.stdout.lower():
                    cron_syntax_issues.append("/etc/crontab: Syntax error")
        
        # Check user crontabs only for non-empty files
        cron_dir = "/var/spool/cron/crontabs"
        if os.path.exists(cron_dir):
            proc = subprocess.run(
                ["find", cron_dir, "-type", "f", "-size", "+0c"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                users = proc.stdout.strip().splitlines()
                for user in users:
                    user_cron = os.path.join(cron_dir, user)
                    with open(user_cron, 'r') as f:
                        content = f.read().strip()
                    
                    if content:  # Only check if not empty
                        proc = subprocess.run(
                            ["bash", "-c", f"cat '{user_cron}' 2>/dev/null | crontab -l - 2>&1 1>/dev/null || echo 'Syntax error detected'"],
                            capture_output=True,
                            text=True
                        )
                        
                        if proc.returncode != 0 or "syntax error" in proc.stdout.lower():
                            cron_syntax_issues.append(f"User cron ({user}): Syntax error")
        
        # Check /etc/cron.d for syntax errors
        cron_d_dir = "/etc/cron.d"
        if os.path.exists(cron_d_dir):
            proc = subprocess.run(
                ["find", cron_d_dir, "-type", "f", "-size", "+0c"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                cron_files = proc.stdout.strip().splitlines()
                for cron_file in cron_files:
                    proc = subprocess.run(
                        ["bash", "-c", f"cat '{cron_file}' 2>/dev/null | crontab -l - 2>&1 1>/dev/null || echo 'Syntax error detected'"],
                        capture_output=True,
                        text=True
                    )
                    
                    if proc.returncode != 0 or "syntax error" in proc.stdout.lower():
                        cron_syntax_issues.append(f"Cron file ({os.path.basename(cron_file)}): Syntax error")
    
    except Exception:
        cron_syntax_issues.append("Cron syntax check: Unable to verify")
    
    return cron_syntax_issues

def check():
    """Comprehensive scheduled tasks check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Cron job check
    cron_issues = _check_cron_jobs()
    if cron_issues:
        details.extend(cron_issues[:5])  # Limit to first 5
        if "Not running" in str(cron_issues):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        remediation = "Check cron service: systemctl status cron && journalctl -u cron"
    else:
        details.append("Cron service: OK")
    
    # Systemd timers check
    timer_issues = _check_systemd_timers()
    if timer_issues:
        details.extend(timer_issues[:5])  # Limit to first 5
        if "Failed" in str(timer_issues):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check systemd timers: systemctl list-timers && systemctl status <timer>"
    else:
        details.append("Systemd timers: OK")
    
    # Cron syntax check
    cron_syntax_issues = _check_cron_syntax()
    if cron_syntax_issues:
        details.extend(cron_syntax_issues[:5])  # Limit to first 5
        worst_status = "CRIT"
        if not remediation:
            remediation = "Fix cron syntax: crontab -e, check /etc/crontab, test with crontab -l"
    else:
        details.append("Cron syntax: OK")
    
    # Main message
    message_parts = []
    message_parts.append(f"Cron issues: {len(cron_issues)}")
    message_parts.append(f"Timer issues: {len(timer_issues)}")
    message_parts.append(f"Syntax errors: {len(cron_syntax_issues)}")
    
    main_message = ", ".join(message_parts)
    
    if worst_status == "OK":
        main_message = "All scheduled tasks healthy"
    
    return Result(
        name="scheduled",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )