import os
import os
import shutil
import subprocess
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def _get_disk_usage():
    """Get disk usage for all mounted filesystems"""
    filesystems = []
    
    try:
        # Get filesystem info
        proc = subprocess.run(
            ["df", "-h", "--output=source,target,fstype,size,used,avail,pcent"],
            capture_output=True,
            text=True
        )
        
        lines = proc.stdout.strip().splitlines()[1:]  # Skip header
        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 6:
                source = parts[0]
                target = parts[1]
                fstype = parts[2]
                size = parts[3]
                used = parts[4] 
                avail = parts[5]
                percent = parts[6].rstrip('%')
                
                # Skip temporary and special filesystems
                if fstype in ['tmpfs', 'devtmpfs', 'proc', 'sysfs', 'devpts']:
                    continue
                    
                filesystems.append({
                    'source': source,
                    'target': target,
                    'fstype': fstype,
                    'size': size,
                    'used': used,
                    'available': avail,
                    'percent_used': float(percent) if percent.replace('.', '').isdigit() else 0
                })
    except Exception as e:
        filesystems.append({'error': str(e)})
    
    return filesystems

def _get_inode_usage():
    """Check inode usage on critical filesystems"""
    inode_info = []
    
    try:
        proc = subprocess.run(
            ["df", "-i", "--output=target,itotal,iused,iusec,pcent"],
            capture_output=True,
            text=True
        )
        
        lines = proc.stdout.strip().splitlines()[1:]  # Skip header
        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 5:
                target = parts[0]
                percent = parts[4].rstrip('%')
                
                if target in ['/', '/home', '/var', '/tmp']:
                    inode_info.append({
                        'target': target,
                        'percent_used': float(percent) if percent.replace('.', '').isdigit() else 0
                    })
    except Exception as e:
        inode_info.append({'error': str(e)})
    
    return inode_info

def _check_smart_health():
    """Check SMART health of disks"""
    smart_issues = []
    
    try:
        # Get list of disks
        disk_devices = []
        for device in os.listdir('/dev/'):
            if device.startswith('sd') and len(device) == 3:
                disk_devices.append(f'/dev/{device}')
        
        for disk in disk_devices:
            try:
                proc = subprocess.run(
                    ["smartctl", "-H", disk],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if proc.returncode != 0:
                    smart_issues.append(f"{disk}: SMART command failed")
                else:
                    output = proc.stdout
                    if "PASSED" not in output:
                        smart_issues.append(f"{disk}: SMART health check failed")
                    elif "FAILING" in output:
                        smart_issues.append(f"{disk}: SMART critical failure")
                        
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # smartctl not available or timeout
                pass
            except Exception as e:
                smart_issues.append(f"{disk}: {str(e)}")
                
    except Exception:
        pass  # smartctl not available
    
    return smart_issues

def _check_raid_status():
    """Check RAID/LVM/ZFS status"""
    raid_issues = []
    
    try:
        # Check mdadm (software RAID)
        if shutil.which('mdadm'):
            proc = subprocess.run(
                ["mdadm", "--detail", "--scan"],
                capture_output=True,
                text=True
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Check each array
                lines = proc.stdout.strip().splitlines()
                for line in lines:
                    if 'ARRAY' in line:
                        array_name = line.split()[-1]
                        detail_proc = subprocess.run(
                            ["mdadm", "--detail", array_name],
                            capture_output=True,
                            text=True
                        )
                        if "State : degraded" in detail_proc.stdout:
                            raid_issues.append(f"RAID array {array_name}: DEGRADED")
                        elif "State : failed" in detail_proc.stdout:
                            raid_issues.append(f"RAID array {array_name}: FAILED")
    
        # Check LVM
        if shutil.which('vgs'):
            proc = subprocess.run(
                ["vgs", "--noheadings", "-o", "vg_name,vg_attr"],
                capture_output=True,
                text=True
            )
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        vg_name = parts[0]
                        vg_attr = parts[1]
                        if 'p' in vg_attr:  # Partial volume group
                            raid_issues.append(f"LVM VG {vg_name}: Partial/degraded")
    
    except Exception:
        pass
    
    return raid_issues

def check():
    """Comprehensive disk and filesystem check"""
    details = []
    worst_status = "OK"
    remediation = None
    
    # Get filesystem usage
    filesystems = _get_disk_usage()
    
    for fs in filesystems:
        if 'error' in fs:
            details.append(f"Error checking filesystems: {fs['error']}")
            worst_status = "BROKE"
            continue
            
        percent = fs['percent_used']
        target = fs['target']
        fstype = fs['fstype']
        
        if target == '/':  # Root filesystem check
            if percent > 90:
                status = "CRIT"
                message = f"Root filesystem {percent:.1f}% used - CRITICAL"
                remediation = f"Free up space in root filesystem: clean /tmp, remove old logs, resize partitions"
            elif percent > 80:
                status = "WARN"
                message = f"Root filesystem {percent:.1f}% used - WARNING"
                remediation = f"Monitor root filesystem usage, consider cleanup"
            else:
                status = "OK"
                message = f"Root filesystem {percent:.1f}% used"
                
            if worst_status == "OK" or (worst_status == "WARN" and status == "CRIT") or (worst_status == "OK" and status in ["WARN", "CRIT"]):
                worst_status = status
                
            details.append(f"{target} ({fstype}): {percent:.1f}% used")
        
        # Network drives check
        if fstype in ['nfs', 'cifs', 'smbfs']:
            # Test if network drive is accessible
            try:
                test_file = f"{target}/.whatbroke_test"
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
            except (OSError, IOError):
                details.append(f"Network drive {target}: Unreachable")
                if worst_status == "OK":
                    worst_status = "WARN"
    
    # Inode usage check
    inode_info = _get_inode_usage()
    for inode in inode_info:
        if 'error' in inode:
            details.append(f"Error checking inodes: {inode['error']}")
            continue
            
        percent = inode['percent_used']
        target = inode['target']
        
        if percent > 90:
            status = "CRIT"
            details.append(f"Inodes {target}: {percent:.1f}% used - CRITICAL")
            if worst_status == "OK":
                worst_status = status
        elif percent > 80:
            status = "WARN"
            details.append(f"Inodes {target}: {percent:.1f}% used - WARNING")
            if worst_status == "OK":
                worst_status = "WARN"
        else:
            details.append(f"Inodes {target}: {percent:.1f}% used")
    
    # SMART health check
    smart_issues = _check_smart_health()
    for issue in smart_issues:
        details.append(f"SMART: {issue}")
        if "critical" in issue.lower() or "failed" in issue.lower():
            worst_status = "CRIT"
        elif worst_status == "OK":
            worst_status = "WARN"
    
    # RAID/LVM check
    raid_issues = _check_raid_status()
    for issue in raid_issues:
        details.append(f"RAID/LVM: {issue}")
        if "FAILED" in issue:
            worst_status = "CRIT"
        elif "DEGRADED" in issue and worst_status == "OK":
            worst_status = "WARN"
    
    # Get root filesystem for main message
    root_fs = next((fs for fs in filesystems if fs.get('target') == '/'), None)
    if root_fs:
        main_message = f"Root filesystem {root_fs['percent_used']:.1f}% used, {len(filesystems)-1} other filesystems checked"
    else:
        main_message = f"Checked {len(filesystems)} filesystems"
    
    return Result(
        name="disk",
        status=worst_status,
        message=main_message,
        details=details,
        remediation=remediation if worst_status in ["WARN", "CRIT"] else None
    )
