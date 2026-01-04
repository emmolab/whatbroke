import os
import socket
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _test_internet_connectivity():
    """Test basic internet connectivity"""
    test_hosts = [
        ("8.8.8.8", "Google DNS"),
        ("1.1.1.1", "Cloudflare DNS"),
        ("9.9.9.9", "Quad9 DNS")
    ]
    
    results = []
    for host, description in test_hosts:
        try:
            proc = subprocess.run(
                ["ping", "-c", "1", "-W", "2", host],
                capture_output=True,
                text=True
            )
            if proc.returncode == 0:
                results.append(f"{host}: OK")
            else:
                results.append(f"{host}: FAIL")
        except Exception:
            results.append(f"{host}: ERROR")
    
    return results

def _test_dns_resolution():
    """Test DNS resolution"""
    test_domains = [
        "google.com",
        "example.com",
        "github.com"
    ]
    
    results = []
    for domain in test_domains:
        try:
            ip = socket.gethostbyname(domain)
            results.append(f"{domain}: {ip}")
        except socket.gaierror:
            results.append(f"{domain}: DNS FAIL")
        except Exception:
            results.append(f"{domain}: ERROR")
    
    return results

def _check_firewall_status():
    """Check firewall status"""
    firewall_info = []
    
    # Check ufw
    try:
        proc = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            status = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "Unknown"
            firewall_info.append(f"UFW: {status}")
    except Exception:
        pass
    
    # Check iptables rules
    try:
        proc = subprocess.run(
            ["iptables", "-L", "-n", "--line-numbers"],
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            rules = len(proc.stdout.strip().splitlines())
            if rules > 10:  # Arbitrary threshold for "many rules"
                firewall_info.append(f"iptables: {rules} rules active")
            else:
                firewall_info.append(f"iptables: {rules} rules")
    except Exception:
        pass
    
    # Check firewalld
    try:
        proc = subprocess.run(
            ["firewall-cmd", "--state"],
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            firewall_info.append(f"firewalld: {proc.stdout.strip()}")
    except Exception:
        pass
    
    return firewall_info

def _get_listening_ports():
    """Get list of listening ports"""
    listening_ports = []
    
    try:
        proc = subprocess.run(
            ["netstat", "-tuln"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            for line in lines[2:]:  # Skip headers
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 5:
                        proto = parts[0]
                        local_address = parts[3]
                        state = parts[5] if len(parts) > 5 else "LISTEN"
                        
                        # Extract port number
                        if ':' in local_address:
                            ip, port = local_address.rsplit(':', 1)
                        else:
                            ip, port = local_address, local_address
                        
                        listening_ports.append({
                            'proto': proto,
                            'ip': ip,
                            'port': port,
                            'state': state
                        })
    
    except Exception:
        pass
    
    return listening_ports

def _check_unexpected_ports():
    """Check for unexpected open ports"""
    # Common service ports and expected protocols
    common_ports = {
        '22': 'SSH',
        '80': 'HTTP',
        '443': 'HTTPS',
        '53': 'DNS',
        '25': 'SMTP',
        '587': 'SMTPS',
        '110': 'POP3',
        '995': 'POP3S',
        '143': 'IMAP',
        '993': 'IMAPS',
        '3306': 'MySQL',
        '5432': 'PostgreSQL',
        '6379': 'Redis',
        '8080': 'HTTP-Alt',
        '8443': 'HTTPS-Alt'
    }
    
    listening_ports = _get_listening_ports()
    unexpected_ports = []
    
    for port_info in listening_ports:
        port = port_info['port']
        proto = port_info['proto']
        
        if port not in common_ports:
            unexpected_ports.append(f"{proto}/{port}: Unexpected service")
        elif proto != common_ports[port].lower():
            unexpected_ports.append(f"{proto}/{port}: Wrong protocol (expected {common_ports[port].lower()})")
    
    return unexpected_ports

def _check_default_route():
    """Check for default network route"""
    try:
        proc = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0 and proc.stdout.strip():
            return True, proc.stdout.strip()
        else:
            return False, "No default route"
    except Exception:
        return False, "Error checking routes"

def check():
    """Comprehensive networking check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Default route check
    has_route, route_info = _check_default_route()
    if has_route:
        details.append(f"Default route: OK")
    else:
        details.append(f"Default route: {route_info}")
        worst_status = "CRIT"
        remediation = "Check network configuration: ip route add default via <gateway>"
    
    # Internet connectivity check
    connectivity_results = _test_internet_connectivity()
    failed_hosts = [r for r in connectivity_results if "FAIL" in r or "ERROR" in r]
    
    if failed_hosts:
        details.extend(connectivity_results)
        if len(failed_hosts) >= 2:
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check network connectivity: ping, traceroute, check firewall"
    else:
        details.append("Internet connectivity: OK")
    
    # DNS resolution check
    dns_results = _test_dns_resolution()
    failed_dns = [r for r in dns_results if "FAIL" in r or "ERROR" in r]
    
    if failed_dns:
        details.extend(dns_results)
        if len(failed_dns) >= 2:
            if worst_status == "OK" or (worst_status == "WARN" and len(failed_dns) >= 2):
                worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check DNS configuration: /etc/resolv.conf, test different DNS servers"
    else:
        details.append("DNS resolution: OK")
    
    # Firewall check
    firewall_info = _check_firewall_status()
    if firewall_info:
        details.extend(firewall_info)
        
        # Check if firewall is disabled (potential security issue)
        disabled_firewalls = [info for info in firewall_info if "inactive" in info.lower() or "not running" in info.lower()]
        if disabled_firewalls:
            details.append("Firewall: DISABLED - Security Risk")
            if worst_status == "OK":
                worst_status = "CRIT"
            if not remediation:
                remediation = "Enable firewall: ufw enable, firewall-cmd --add-service, iptables rules"
    
    # Port check
    unexpected_ports = _check_unexpected_ports()
    listening_ports = _get_listening_ports()
    
    if unexpected_ports:
        details.extend(unexpected_ports)
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Review unexpected ports: netstat -tuln, check firewall rules"
    else:
        details.append(f"Listening ports: {len(listening_ports)} (all expected)")
    
    # Main message
    message_parts = []
    message_parts.append(f"Default route: {'OK' if has_route else 'FAIL'}")
    message_parts.append(f"Internet connectivity: {len(failed_hosts)} failed")
    message_parts.append(f"DNS resolution: {len(failed_dns)} failed")
    message_parts.append(f"Listening ports: {len(listening_ports)}")
    message_parts.append(f"Unexpected ports: {len(unexpected_ports)}")
    
    main_message = ", ".join(message_parts)
    
    if worst_status == "OK":
        main_message = "All networking checks passed"
    
    return Result(
        name="networking",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )
