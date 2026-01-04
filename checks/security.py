import os
import shutil
import subprocess
import sys
import re
from datetime import datetime, timedelta

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _check_failed_logins():
    """Check for failed login attempts"""
    failed_logins = []
    failed_count = 0
    
    try:
        # Check auth.log for failed logins
        auth_log = "/var/log/auth.log"
        if not os.path.exists(auth_log):
            auth_log = "/var/log/secure"  # RHEL/CentOS
        
        if os.path.exists(auth_log):
            # Get last 1000 lines of auth log
            proc = subprocess.run(
                ["tail", "-n", "1000", auth_log],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                failed_count = 0
                
                for line in lines:
                    if "failed" in line.lower() or "authentication failure" in line.lower():
                        failed_count += 1
                        if failed_count <= 10:  # Show first 10
                            failed_logins.append(line.strip()[:200])  # Limit length
                
                if failed_count > 0:
                    failed_logins.insert(0, f"Total failed logins: {failed_count}")
    
    except Exception:
        pass
    
    return failed_count, failed_logins

def _check_pending_updates():
    """Check for pending security updates"""
    update_info = []
    
    try:
        # Check for apt-based systems
        if shutil.which('apt') and os.path.exists('/etc/apt'):
            proc = subprocess.run(
                ["bash", "-c", "apt list --upgradable 2>/dev/null | wc -l"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                try:
                    upgradable_count = int(proc.stdout.strip())
                    
                    if upgradable_count > 0:
                        update_info.append(f"Pending updates: {upgradable_count}")
                        
                        # Check for security updates
                        proc = subprocess.run(
                            ["bash", "-c", "apt list --upgradable 2>/dev/null | grep -i security | wc -l"],
                            capture_output=True,
                            text=True
                        )
                        
                        if proc.returncode == 0 and proc.stdout.strip():
                            security_count = int(proc.stdout.strip())
                            update_info.append(f"Security updates: {security_count}")
                except ValueError:
                    # Fallback if parsing fails
                    update_info.append("Updates available but count unclear")
    
    except Exception:
        pass
    
    try:
        # Check for yum/dnf-based systems
        if shutil.which('dnf'):
            proc = subprocess.run(
                ["dnf", "check-update"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 100:  # Updates available
                lines = proc.stdout.strip().splitlines()
                update_count = len(lines) - 1  # Subtract header line
                update_info.append(f"Pending updates: {update_count}")
                
                # Look for security updates
                security_count = sum(1 for line in lines if 'security' in line.lower())
                if security_count > 0:
                    update_info.append(f"Security updates: {security_count}")
        
        elif shutil.which('yum'):
            proc = subprocess.run(
                ["yum", "check-update"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 100:  # Updates available
                lines = proc.stdout.strip().splitlines()
                update_count = len(lines) - 1  # Subtract header line
                update_info.append(f"Pending updates: {update_count}")
                
                security_count = sum(1 for line in lines if 'security' in line.lower())
                if security_count > 0:
                    update_info.append(f"Security updates: {security_count}")
    
    except Exception:
        pass
    
    return update_info

def _check_ssh_config():
    """Check SSH configuration for security issues"""
    ssh_issues = []
    
    try:
        sshd_config = "/etc/ssh/sshd_config"
        if os.path.exists(sshd_config):
            with open(sshd_config, 'r') as f:
                config_lines = f.readlines()
            
            # Check for insecure configurations
            for line in config_lines:
                line = line.strip().lower()
                if line.startswith('#') or not line:
                    continue
                
                if 'permitrootlogin yes' in line:
                    ssh_issues.append("SSH: Root login enabled - Security risk")
                elif 'passwordauthentication yes' in line:
                    ssh_issues.append("SSH: Password authentication enabled - Security risk")
                elif 'permitemptypasswords yes' in line:
                    ssh_issues.append("SSH: Empty passwords allowed - Critical security risk")
                elif 'protocol 1' in line:
                    ssh_issues.append("SSH: Protocol 1 enabled - Insecure protocol")
        
        # Check if SSH daemon is running
        proc = subprocess.run(
            ["systemctl", "is-active", "ssh"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode != 0:
            # Try sshd
            proc = subprocess.run(
                ["systemctl", "is-active", "sshd"],
                capture_output=True,
                text=True
            )
            
            if "active" in proc.stdout:
                ssh_issues.append("SSH daemon is running - Ensure configuration is secure")
    
    except Exception:
        pass
    
    return ssh_issues

def _check_firewall_status():
    """Check firewall configuration for security issues"""
    firewall_issues = []
    
    try:
        # Check ufw status
        if shutil.which('ufw'):
            proc = subprocess.run(
                ["ufw", "status"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                output = proc.stdout.strip()
                if "inactive" in output.lower():
                    firewall_issues.append("Firewall: UFW is inactive - Security risk")
                elif "Status: inactive" in output:
                    firewall_issues.append("Firewall: UFW is inactive - Security risk")
        
        # Check iptables
        if not firewall_issues and shutil.which('iptables'):
            proc = subprocess.run(
                ["bash", "-c", "iptables -L -n | grep -c '^[^#\\|^Chain\\|ACCEPT\\|DROP\\|REJECT' 2>/dev/null || echo '0'"],
                capture_output=True,
                text=True
            )
            
            try:
                rules_count = int(proc.stdout.strip())
                if rules_count == 0:
                    firewall_issues.append("Firewall: No iptables rules - Security risk")
            except ValueError:
                pass
        
        # Check firewalld
        if not firewall_issues and shutil.which('firewall-cmd'):
            proc = subprocess.run(
                ["firewall-cmd", "--state"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0 and "not running" in proc.stdout.lower():
                firewall_issues.append("Firewall: Firewalld is not running - Security risk")
    
    except Exception:
        pass
    
    return firewall_issues

def _check_sudoers():
    """Check sudoers file for syntax errors"""
    sudoers_issues = []
    
    try:
        proc = subprocess.run(
            ["visudo", "-c"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode != 0:
            sudoers_issues.append(f"Sudoers syntax error: {proc.stderr}")
        else:
            # Check for dangerous sudo rules
            sudoers_file = "/etc/sudoers"
            if os.path.exists(sudoers_file):
                with open(sudoers_file, 'r') as f:
                    content = f.read()
                
                # Look for NOPASSWD rules that might be dangerous
                if 'NOPASSWD' in content:
                    sudoers_issues.append("Sudoers: NOPASSWD rules found - Review for security")
    
    except Exception:
        pass
    
    return sudoers_issues

def _check_certificates():
    """Check for expiring SSL/TLS certificates"""
    expiring_certs = []
    
    try:
        # Common certificate directories
        cert_paths = [
            "/etc/ssl/certs",
            "/etc/pki/tls/certs",
            "/usr/local/share/ca-certificates"
        ]
        
        current_date = datetime.now()
        
        for cert_dir in cert_paths:
            if os.path.exists(cert_dir):
                proc = subprocess.run(
                    ["find", cert_dir, "-name", "*.crt", "-o", "-name", "*.pem"],
                    capture_output=True,
                    text=True
                )
                
                if proc.returncode == 0:
                    cert_files = proc.stdout.strip().splitlines()
                    
                    for cert_file in cert_files[:20]:  # Limit to 20 certs
                        try:
                            # Check certificate expiration
                            proc = subprocess.run(
                                ["openssl", "x509", "-in", cert_file, "-noout", "-dates"],
                                capture_output=True,
                                text=True
                            )
                            
                            if proc.returncode == 0:
                                # Extract expiration date
                                for line in proc.stdout.splitlines():
                                    if 'notAfter=' in line:
                                        date_str = line.split('=')[1].strip()
                                        try:
                                            exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                                            days_until_exp = (exp_date - current_date).days
                                            
                                            if days_until_exp < 0:
                                                expiring_certs.append(f"{cert_file}: EXPIRED ({abs(days_until_exp)} days ago)")
                                            elif days_until_exp <= 30:
                                                expiring_certs.append(f"{cert_file}: Expires in {days_until_exp} days")
                                        except ValueError:
                                            continue
                        
                        except Exception:
                            continue
    
    except Exception:
        pass
    
    return expiring_certs

def check():
    """Comprehensive security and integrity check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Failed logins check
    failed_count, failed_logins = _check_failed_logins()
    if failed_count > 3:
        details.extend(failed_logins[:10])  # Show first 10
        if failed_count > 10:
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        remediation = "Review failed logins: check auth.log, implement fail2ban"
    elif failed_count > 0:
        details.append(f"Failed logins: {failed_count} (within threshold)")
    else:
        details.append("Failed logins: OK")
    
    # Pending updates check
    update_info = _check_pending_updates()
    if update_info:
        details.extend(update_info)
        
        # Check for critical security updates
        security_updates = [info for info in update_info if "security" in info.lower()]
        if security_updates:
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        
        if not remediation:
            remediation = "Install security updates: apt upgrade, dnf update, yum update"
    else:
        details.append("System updates: Up to date")
    
    # SSH configuration check
    ssh_issues = _check_ssh_config()
    if ssh_issues:
        details.extend(ssh_issues)
        if "Critical" in ssh_issues[0]:
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Secure SSH: disable root login, use key-based auth only"
    else:
        details.append("SSH configuration: Secure")
    
    # Firewall status check
    firewall_issues = _check_firewall_status()
    if firewall_issues:
        details.extend(firewall_issues)
        if "inactive" in str(firewall_issues) or "Security risk" in str(firewall_issues):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Configure firewall: ufw enable, firewall-cmd --add-service"
    else:
        details.append("Firewall: Configured")
    
    # Sudoers check
    sudoers_issues = _check_sudoers()
    if sudoers_issues:
        details.extend(sudoers_issues)
        if "syntax error" in str(sudoers_issues):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Fix sudoers: visudo -c, review NOPASSWD rules"
    else:
        details.append("Sudoers configuration: OK")
    
    # Certificate check
    expiring_certs = _check_certificates()
    if expiring_certs:
        details.extend(expiring_certs[:10])
        if "EXPIRED" in str(expiring_certs):
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Renew expiring certificates: certbot, purchase new certs"
    else:
        details.append("SSL certificates: All valid")
    
    # Main message
    message_parts = []
    message_parts.append(f"Failed logins: {failed_count}")
    message_parts.append(f"Pending updates: {len(update_info)}")
    message_parts.append(f"SSH issues: {len(ssh_issues)}")
    message_parts.append(f"Firewall issues: {len(firewall_issues)}")
    message_parts.append(f"Sudoers issues: {len(sudoers_issues)}")
    message_parts.append(f"Expiring certs: {len(expiring_certs)}")
    
    main_message = ", ".join(message_parts)
    
    if worst_status == "OK":
        main_message = "All security checks passed"
    
    return Result(
        name="security",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )