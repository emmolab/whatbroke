import os
import re
import subprocess

from ..result import Result, escalate


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _docker_available() -> bool:
    try:
        proc = _run(["docker", "info"], timeout=5)
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _parse_exit_code(status: str, inspect_exit_code: str | None = None) -> int | None:
    if inspect_exit_code is not None:
        try:
            return int(str(inspect_exit_code).strip())
        except (TypeError, ValueError):
            pass

    match = re.search(r"Exited \((\d+)\)", status)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _get_exited_containers() -> list:
    """Return list of human-readable strings for non-zero exited containers."""
    try:
        proc = _run(
            ["docker", "ps", "-a", "--filter", "status=exited",
             "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"],
            timeout=10,
        )
        containers = []
        for line in proc.stdout.strip().splitlines():
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            cid, name, status, image = parts[0][:12], parts[1], parts[2], parts[3]
            inspect_exit_code = None
            try:
                ins = _run(
                    ["docker", "inspect", cid,
                     "--format", "{{.State.ExitCode}}"],
                    timeout=3,
                )
                inspect_exit_code = ins.stdout.strip()
            except Exception:
                pass

            exit_code = _parse_exit_code(status, inspect_exit_code)
            if exit_code is None or exit_code == 0:
                continue

            containers.append(
                f"{name} [{cid}] — {status} (exit {exit_code}) — image: {image}")
        return containers
    except Exception:
        return []


def _get_restarting_containers() -> list:
    """Return list of containers in a restart loop with restart count."""
    try:
        proc = _run(
            ["docker", "ps",
             "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"],
            timeout=10,
        )
        containers = []
        for line in proc.stdout.strip().splitlines():
            if "restarting" not in line.lower():
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            cid, name, status, image = parts[0][:12], parts[1], parts[2], parts[3]
            restart_count = "?"
            try:
                ins = _run(
                    ["docker", "inspect", cid,
                     "--format", "{{.RestartCount}}"],
                    timeout=3,
                )
                restart_count = ins.stdout.strip()
            except Exception:
                pass
            containers.append(
                f"{name} [{cid}] — {status} (restarts: {restart_count}) — image: {image}")
        return containers
    except Exception:
        return []


def _check_kubernetes() -> list:
    """Return list of Kubernetes issue strings."""
    issues = []
    try:
        proc = _run(["kubectl", "version", "--client"], timeout=5)
        if proc.returncode != 0:
            return issues
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return issues

    # Nodes
    try:
        proc = _run(["kubectl", "get", "nodes", "--no-headers"], timeout=10)
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                if "NotReady" in line:
                    node = line.split()[0]
                    issues.append(f"Node {node}: NotReady")
    except Exception:
        pass

    # Pods
    try:
        proc = _run(
            ["kubectl", "get", "pods", "--all-namespaces",
             "--no-headers", "--field-selector=status.phase!=Running"],
            timeout=15,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[:20]:
                parts = line.split()
                if len(parts) >= 4:
                    ns, name, ready, phase = parts[0], parts[1], parts[2], parts[3]
                    if phase in ("CrashLoopBackOff", "Error", "OOMKilled", "Evicted"):
                        issues.append(f"Pod {ns}/{name}: {phase}")
    except Exception:
        pass
    return issues


def _check_libvirt() -> tuple[list[str], list[str]]:
    """Return (issues, notes) for libvirt VMs on virtualisation hosts."""
    issues = []
    notes = []
    if not os.path.exists('/var/lib/libvirt'):
        return issues, notes
    try:
        proc = _run(["systemctl", "is-active", "libvirtd"], timeout=5)
        if "active" not in proc.stdout:
            issues.append("libvirtd: not running")
            return issues, notes

        proc = _run(["virsh", "list", "--all"], timeout=10)
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[2:]:
                parts = line.split()
                if len(parts) >= 3:
                    name = parts[1]
                    state = " ".join(parts[2:]).lower()
                    if "paused" in state:
                        issues.append(f"VM {name}: paused")
                    elif "shut off" in state:
                        notes.append(f"VM {name}: shut off (not alerting by default)")
    except Exception:
        pass
    return issues, notes


def check() -> Result:
    """Docker containers, Kubernetes cluster health, libvirt VMs."""
    details = []
    status  = "OK"
    remediation_parts = []

    exited = []
    restarting = []
    k8s_issues = []
    vm_issues = []

    # Docker
    docker_up = _docker_available()
    if not docker_up:
        details.append("Docker: not running or not installed (skipping container checks)")
    else:
        details.append("Docker: daemon running")

        exited = _get_exited_containers()
        if exited:
            details.append(f"Exited containers: {len(exited)}")
            details.extend([f"  {c}" for c in exited[:5]])
            if len(exited) > 5:
                details.append(f"  ...and {len(exited) - 5} more")
            status = escalate(status, "WARN")
            remediation_parts.append("Inspect failed containers first with: docker ps -a --filter status=exited and docker logs <container>")
            remediation_parts.append("Remove exited containers only after confirming they are safe to discard")
        else:
            details.append("Docker containers: none exited")

        restarting = _get_restarting_containers()
        if restarting:
            details.append(f"Restarting containers: {len(restarting)}")
            details.extend([f"  {c}" for c in restarting[:3]])
            status = escalate(status, "WARN")
            remediation_parts.append("Inspect restart loops with: docker logs <container> and docker inspect <container>")

    # Kubernetes
    k8s_issues = _check_kubernetes()
    if k8s_issues:
        details.append(f"Kubernetes issues: {len(k8s_issues)}")
        details.extend(k8s_issues[:10])
        sev = "CRIT" if any(
            kw in str(k8s_issues)
            for kw in ("CrashLoopBackOff", "NotReady", "OOMKilled")
        ) else "WARN"
        status = escalate(status, sev)
        remediation_parts.append("Inspect affected workloads with: kubectl describe pod <name> -n <ns>")
    else:
        # Only report k8s status if kubectl is available
        try:
            proc = _run(["kubectl", "version", "--client"], timeout=3)
            if proc.returncode == 0:
                details.append("Kubernetes: cluster appears healthy")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # libvirt VMs
    vm_issues, vm_notes = _check_libvirt()
    if vm_issues:
        details.append(f"VMs: {len(vm_issues)} actionable issue(s)")
        details.extend(vm_issues[:5])
        status = escalate(status, "WARN")
        remediation_parts.append("Investigate paused guests with: virsh domstate <name> and virsh resume <name> if appropriate")
    elif os.path.exists('/var/lib/libvirt'):
        details.append("VMs: no paused guests detected")

    if vm_notes:
        details.append(f"VMs intentionally inactive or stopped: {len(vm_notes)}")
        details.extend(vm_notes[:5])

    # Message
    if status == "OK":
        msg = "All container/virtualisation checks passed"
    else:
        parts = []
        if exited if docker_up else []:
            parts.append(f"{len(exited)} exited containers")
        if k8s_issues:
            parts.append(f"{len(k8s_issues)} k8s issue(s)")
        if vm_issues:
            parts.append(f"{len(vm_issues)} VM issue(s)")
        msg = ", ".join(parts) if parts else "container issues detected"

    remediation = "\n".join(dict.fromkeys(remediation_parts)) if status != "OK" and remediation_parts else None

    return Result(
        name="containers",
        status=status,
        message=msg,
        details=details,
        remediation=remediation,
    )
