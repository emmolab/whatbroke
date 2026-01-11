import os
import subprocess
import sys
import re

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _check_docker_status():
    """Check if Docker daemon is running"""
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return proc.returncode == 0, proc.stdout if proc.returncode == 0 else proc.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "Docker not installed or timeout"

def _get_exited_containers():
    """Get list of exited containers with detailed information"""
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--filter", "status=exited", 
             "--format", "{{.ID}} {{.Names}} {{.Status}} {{.Image}}"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            containers = []
            lines = proc.stdout.strip().splitlines()
            # Skip header line if present
            start_idx = 1 if lines and 'CONTAINER ID' in lines[0] else 0
            for line in lines[start_idx:]:
                if line.strip():
                    # Split by spaces but keep the status (which may contain spaces) together
                    # Format: ID Name Status Image
                    # Status may have multiple words like "Exited (0) 5 minutes ago"
                    words = line.split()
                    if len(words) >= 4:
                        container_id = words[0][:12]
                        name = words[1]
                        # Status is everything between name and image
                        # Find where image starts (usually the last word)
                        # But we need to be smarter about it
                        # For now, assume status is words[2:-1] and image is words[-1]
                        if len(words) > 4:
                            status = ' '.join(words[2:-1])
                            image = words[-1]
                        else:
                            status = words[2]
                            image = words[3] if len(words) > 3 else "unknown"
                        
                        # Get exit code
                        try:
                            inspect_proc = subprocess.run(
                                ["docker", "inspect", container_id, "--format", "{{.State.ExitCode}}"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            exit_code = inspect_proc.stdout.strip()
                            if exit_code and exit_code not in status:
                                status += f" (exit code: {exit_code})"
                        except:
                            pass
                        
                        containers.append(f"{name} ({container_id}): {status} [image: {image}]")
            return containers
        return []
    except Exception:
        return []

def _get_restarting_containers():
    """Get containers that are frequently restarting with details"""
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}} {{.Names}} {{.Status}} {{.Image}}"],
            capture_output=True,
            text=True
        )
        
        restarting_containers = []
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            for line in lines:
                if line.strip() and "restarting" in line.lower():
                    words = line.split()
                    if len(words) >= 4:
                        container_id = words[0][:12]
                        name = words[1]
                        # Status is everything between name and image
                        if len(words) > 4:
                            status = ' '.join(words[2:-1])
                            image = words[-1]
                        else:
                            status = words[2]
                            image = words[3] if len(words) > 3 else "unknown"
                        
                        # Get restart count
                        try:
                            inspect_proc = subprocess.run(
                                ["docker", "inspect", container_id, "--format", "{{.RestartCount}}"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            restart_count = inspect_proc.stdout.strip()
                            if restart_count and restart_count != "0":
                                status += f" (restarts: {restart_count})"
                        except:
                            pass
                        
                        restarting_containers.append(f"{name} ({container_id}): {status} [image: {image}]")
        
        return restarting_containers
    except Exception:
        return []

def _check_kubernetes_status():
    """Check Kubernetes node and pod status"""
    k8s_issues = []
    
    try:
        # Check kubectl availability
        proc = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if proc.returncode != 0:
            return k8s_issues
        
        # Check node status
        proc = subprocess.run(
            ["kubectl", "get", "nodes", "--no-headers"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            nodes = proc.stdout.strip().splitlines()
            for line in nodes:
                if "NotReady" in line:
                    node_name = line.split()[0]
                    k8s_issues.append(f"Node {node_name}: NotReady")
        
        # Check pod status
        proc = subprocess.run(
            ["kubectl", "get", "pods", "--all-namespaces", "--no-headers"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            pods = proc.stdout.strip().splitlines()
            crashloop_pods = []
            for line in pods:
                if "CrashLoopBackOff" in line or "Error" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        namespace = parts[0]
                        pod_name = parts[1]
                        status = parts[2]
                        crashloop_pods.append(f"Pod {pod_name} (ns {namespace}): {status}")
            
            if crashloop_pods:
                k8s_issues.extend(crashloop_pods[:10])  # Limit to 10 pods
        
    except Exception:
        pass  # kubectl not available or no permissions
    
    return k8s_issues

def _check_vm_status():
    """Check VM host status for virtualization hosts"""
    vm_issues = []
    
    try:
        # Check if we're on a VM host
        if not os.path.exists('/var/lib/libvirt'):
            return vm_issues
        
        # Check libvirt daemon
        proc = subprocess.run(
            ["systemctl", "is-active", "libvirtd"],
            capture_output=True,
            text=True
        )
        
        if "active" not in proc.stdout:
            vm_issues.append("Libvirt daemon not running")
        else:
            # Check running VMs
            proc = subprocess.run(
                ["virsh", "list", "--all"],
                capture_output=True,
                text=True
            )
            
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                vm_states = {}
                
                for line in lines[2:]:  # Skip headers
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 3:
                            vm_id = parts[0]
                            vm_name = parts[1]
                            vm_state = parts[2]
                            vm_states[vm_name] = vm_state
                
                # Check for issues
                for vm_name, state in vm_states.items():
                    if "shut off" in state:
                        vm_issues.append(f"VM {vm_name}: Shutdown")
                    elif "paused" in state:
                        vm_issues.append(f"VM {vm_name}: Paused")
    
    except Exception:
        pass
    
    return vm_issues

def check():
    """Comprehensive container and virtualization check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Docker status check
    docker_running, docker_info = _check_docker_status()
    if not docker_running:
        details.append("Docker: Not running or not installed")
        worst_status = "WARN"
    else:
        details.append("Docker: Running")
        
        # Check exited containers
        exited_containers = _get_exited_containers()
        if exited_containers:
            details.append(f"Docker: Found {len(exited_containers)} exited container(s)")
            for container in exited_containers[:5]:  # Show first 5 in detail
                details.append(f"  → {container}")
            if len(exited_containers) > 5:
                details.append(f"  → ... and {len(exited_containers) - 5} more")
            if worst_status == "OK":
                worst_status = "WARN"
            remediation = "Clean up exited containers: docker rm <container> || docker system prune"
        else:
            details.append("Docker: All running containers healthy")
        
        # Check restarting containers
        restarting_containers = _get_restarting_containers()
        if restarting_containers:
            details.append(f"Docker: Found {len(restarting_containers)} restarting container(s)")
            for container in restarting_containers[:3]:  # Show first 3 in detail
                details.append(f"  → {container}")
            if len(restarting_containers) > 3:
                details.append(f"  → ... and {len(restarting_containers) - 3} more")
            if worst_status == "OK":
                worst_status = "WARN"
            if not remediation:
                remediation = "Check restarting containers: docker logs <container> || docker inspect <container>"
    
    # Kubernetes check
    k8s_issues = _check_kubernetes_status()
    if k8s_issues:
        details.extend([f"Kubernetes: {issue}" for issue in k8s_issues[:10]])
        if "NotReady" in str(k8s_issues) or "CrashLoopBackOff" in str(k8s_issues):
            if worst_status == "OK" or (worst_status == "WARN" and "CrashLoopBackOff" in str(k8s_issues)):
                worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check cluster: kubectl get nodes,pods && kubectl describe <pod>"
    else:
        # Check if k8s tools are available
        try:
            subprocess.run(["kubectl", "version", "--client"], capture_output=True, timeout=2)
            details.append("Kubernetes: Cluster healthy")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            details.append("Kubernetes: Tools not available")
    
    # VM host check
    vm_issues = _check_vm_status()
    if vm_issues:
        details.extend([f"Virtualization: {issue}" for issue in vm_issues[:5]])
        if worst_status == "OK":
            worst_status = "WARN"
        if not remediation:
            remediation = "Check VM status: virsh list && virsh start <vm>"
    else:
        if os.path.exists('/var/lib/libvirt'):
            details.append("Virtualization: VMs healthy")
    
    # Main message
    message_parts = []
    if docker_running:
        message_parts.append(f"Docker containers OK")
    else:
        message_parts.append(f"Docker unavailable")
    
    if k8s_issues:
        message_parts.append(f"K8s issues: {len(k8s_issues)}")
    else:
        message_parts.append(f"K8s OK")
    
    if vm_issues:
        message_parts.append(f"VM issues: {len(vm_issues)}")
    else:
        message_parts.append(f"VMs OK")
    
    main_message = ", ".join(message_parts)
    
    return Result(
        name="containers",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation
    )
