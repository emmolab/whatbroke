import os
import shutil
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _get_disk_usage():
    """Return list of dicts for all non-virtual mounted filesystems."""
    filesystems = []
    skip_types = frozenset(
        ['tmpfs', 'devtmpfs', 'proc', 'sysfs', 'devpts',
         'cgroup', 'cgroup2', 'pstore', 'securityfs', 'debugfs',
         'tracefs', 'configfs', 'fusectl', 'hugetlbfs', 'mqueue',
         'ramfs', 'squashfs', 'overlay', 'efivarfs', 'bpf',
         'autofs', 'rpc_pipefs', 'nfsd']
    )
    try:
        proc = _run(
            ["df", "-h", "--output=source,target,fstype,size,used,avail,pcent"],
            timeout=15,
        )
        for line in proc.stdout.strip().splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            source, target, fstype = parts[0], parts[1], parts[2]
            size, used, avail = parts[3], parts[4], parts[5]
            pct_str = parts[6].rstrip('%')
            if fstype in skip_types:
                continue
            # Skip FUSE mounts under /tmp — AppImages and similar are RO by design
            if fstype.startswith("fuse.") and target.startswith("/tmp/"):
                continue
            filesystems.append({
                'source':       source,
                'target':       target,
                'fstype':       fstype,
                'size':         size,
                'used':         used,
                'available':    avail,
                'percent_used': float(pct_str) if pct_str.replace('.', '').isdigit() else 0,
            })
    except Exception as exc:
        filesystems.append({'error': str(exc)})
    return filesystems


def _get_inode_usage():
    """Return inode usage for critical mount points."""
    inode_info = []
    watch = frozenset(['/', '/home', '/var', '/tmp', '/boot'])
    try:
        proc = _run(["df", "-i", "--output=target,iused,ifree,ipcent"], timeout=15)
        for line in proc.stdout.strip().splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            target = parts[0]
            pct_str = parts[3].rstrip('%')
            if target not in watch:
                continue
            inode_info.append({
                'target':       target,
                'percent_used': float(pct_str) if pct_str.replace('.', '').isdigit() else 0,
            })
    except Exception as exc:
        inode_info.append({'error': str(exc)})
    return inode_info


def _check_smart_health():
    """Return list of SMART issue strings (empty = all OK or tool absent)."""
    issues = []
    if not shutil.which('smartctl'):
        return issues
    try:
        for device in sorted(os.listdir('/dev/')):
            if device.startswith('sd'):
                # sda, sdb … are whole disks; sda1, sda2 … are partitions — skip them
                if len(device) != 3 or not device[2].isalpha():
                    continue
            elif device.startswith('nvme'):
                # nvme0n1 is a whole disk; nvme0n1p1 is a partition — skip partitions
                if 'p' in device.split('n')[-1]:
                    continue
            else:
                continue
            dev_path = f'/dev/{device}'
            try:
                proc = _run(["smartctl", "-H", dev_path], timeout=15)
                out = proc.stdout
                if "PASSED" not in out and "OK" not in out:
                    issues.append(f"{dev_path}: SMART health check failed")
                if "FAILING_NOW" in out or "Reallocated_Sector" in out:
                    issues.append(f"{dev_path}: SMART attributes indicate imminent failure")
            except subprocess.TimeoutExpired:
                issues.append(f"{dev_path}: SMART check timed out")
            except Exception:
                pass
    except Exception:
        pass
    return issues


def _check_readonly_remounts():
    """Detect filesystems that were remounted read-only (usually due to I/O errors).

    Returns a list of (mountpoint, device) tuples for affected mounts.
    """
    # These types are always or often read-only by design — don't alert on them.
    _SKIP_TYPES = frozenset([
        'proc', 'sysfs', 'devtmpfs', 'devpts', 'tmpfs', 'ramfs',
        'cgroup', 'cgroup2', 'pstore', 'securityfs', 'debugfs',
        'tracefs', 'configfs', 'fusectl', 'hugetlbfs', 'mqueue',
        'squashfs', 'iso9660', 'udf', 'overlay', 'efivarfs',
        'bpf', 'autofs', 'rpc_pipefs', 'nfsd', 'fuse.portal',
    ])

    affected = []
    try:
        with open("/proc/mounts") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 4:
                    continue
                device, mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]
                if fstype in _SKIP_TYPES:
                    continue
                # FUSE filesystems (AppImage, gvfs, sshfs, etc.) are often intentionally RO
                if fstype.startswith("fuse."):
                    continue
                # ro appears as the first option or comma-separated; rw means writable
                opt_set = set(options.split(","))
                if "ro" in opt_set and "rw" not in opt_set:
                    affected.append((mountpoint, device, fstype))
    except OSError:
        pass
    return affected


def _check_raid_lvm():
    """Return list of RAID/LVM degraded/failed strings."""
    issues = []
    try:
        if shutil.which('mdadm'):
            proc = _run(["mdadm", "--detail", "--scan"], timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                for line in proc.stdout.splitlines():
                    if 'ARRAY' not in line:
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    # last token that looks like a path
                    array = next((p for p in reversed(parts) if p.startswith('/dev/')), None)
                    if not array:
                        continue
                    try:
                        detail = _run(["mdadm", "--detail", array], timeout=10)
                        if "State : degraded" in detail.stdout:
                            issues.append(f"RAID {array}: degraded")
                        elif "State : failed" in detail.stdout:
                            issues.append(f"RAID {array}: failed")
                    except Exception:
                        pass

        if shutil.which('vgs'):
            proc = _run(["vgs", "--noheadings", "-o", "vg_name,vg_attr"], timeout=10)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    vg_name, vg_attr = parts[0], parts[1]
                    if 'p' in vg_attr:
                        issues.append(f"LVM VG {vg_name}: partial/degraded")
    except Exception:
        pass
    return issues


def check() -> Result:
    """Disk usage, inodes, SMART health, RAID/LVM status."""
    details = []
    status = "OK"
    remediation = None

    filesystems = _get_disk_usage()
    crit_fss, warn_fss = [], []

    for fs in filesystems:
        if 'error' in fs:
            details.append(f"Filesystem error: {fs['error']}")
            status = escalate(status, "BROKE")
            continue

        pct    = fs['percent_used']
        target = fs['target']
        fstype = fs['fstype']
        label  = f"{target} ({fstype})"

        if pct >= 90:
            crit_fss.append(f"{label}: {pct:.0f}% used  [{fs['used']}/{fs['size']}]")
            status = escalate(status, "CRIT")
        elif pct >= 80:
            warn_fss.append(f"{label}: {pct:.0f}% used  [{fs['used']}/{fs['size']}]")
            status = escalate(status, "WARN")
        else:
            details.append(f"{label}: {pct:.0f}% used  [{fs['used']}/{fs['size']}]")

        # Network drive accessibility
        if fstype in ('nfs', 'nfs4', 'cifs', 'smbfs'):
            try:
                os.stat(target)
            except OSError:
                details.append(f"Network mount {target}: unreachable")
                status = escalate(status, "WARN")

    if crit_fss:
        details = [f"CRITICAL - disk full: {f}" for f in crit_fss] + details
        remediation = "Free space: clean /tmp, rotate logs, remove old packages"
    if warn_fss:
        insert_at = len(crit_fss)
        for f in warn_fss:
            details.insert(insert_at, f"WARNING  - disk filling: {f}")
            insert_at += 1
        if not remediation:
            remediation = "Monitor disk usage; plan cleanup or expansion"

    # Inodes
    for inode in _get_inode_usage():
        if 'error' in inode:
            details.append(f"Inode check error: {inode['error']}")
            continue
        pct, target = inode['percent_used'], inode['target']
        if pct >= 90:
            details.append(f"Inodes {target}: {pct:.0f}% used — CRITICAL")
            status = escalate(status, "CRIT")
            remediation = remediation or "Remove small files or increase inode count"
        elif pct >= 80:
            details.append(f"Inodes {target}: {pct:.0f}% used — WARNING")
            status = escalate(status, "WARN")
        else:
            details.append(f"Inodes {target}: {pct:.0f}% used")

    # Read-only remounts (I/O error protection)
    for mountpoint, device, fstype in _check_readonly_remounts():
        details.insert(0, f"READ-ONLY remount: {mountpoint} ({device}, {fstype}) — likely I/O errors")
        status = escalate(status, "CRIT")
        remediation = remediation or "Check kernel log for I/O errors: journalctl -k | grep -i 'error\\|remount\\|EXT4'"

    # SMART
    for issue in _check_smart_health():
        details.append(f"SMART: {issue}")
        sev = "CRIT" if "failure" in issue.lower() else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Back up data immediately; replace failing drive"

    # RAID/LVM
    for issue in _check_raid_lvm():
        details.append(f"Storage: {issue}")
        sev = "CRIT" if "failed" in issue else "WARN"
        status = escalate(status, sev)
        remediation = remediation or "Investigate storage array — data may be at risk"

    root_fs = next((f for f in filesystems if f.get('target') == '/'), None)
    if root_fs:
        msg = (f"Root {root_fs['percent_used']:.0f}% used, "
               f"{len([f for f in filesystems if 'error' not in f])} filesystems checked")
    else:
        msg = f"{len(filesystems)} filesystems checked"

    if status == "OK":
        msg = f"All filesystems healthy — {msg}"

    return Result(
        name="disk",
        status=status,
        message=msg,
        details=details,
        remediation=remediation if status != "OK" else None,
    )
