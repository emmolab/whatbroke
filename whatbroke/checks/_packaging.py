import pathlib
import shutil


def read_os_release_tokens() -> set[str]:
    tokens: set[str] = set()
    path = pathlib.Path("/etc/os-release")
    try:
        for line in path.read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key not in {"ID", "ID_LIKE"}:
                continue
            tokens.update(part for part in value.strip().strip('"').lower().split() if part)
    except OSError:
        pass
    return tokens


def detect_package_kind() -> str | None:
    """Best-effort host package family detection that avoids mixed-tool false positives."""
    tokens = read_os_release_tokens()

    rpm_families = {"rhel", "fedora", "centos", "rocky", "alma", "suse", "opensuse"}
    deb_families = {"debian", "ubuntu"}

    if tokens & rpm_families and shutil.which("rpm"):
        return "rpm"
    if tokens & deb_families and shutil.which("dpkg"):
        return "deb"
    if any(shutil.which(tool) for tool in ("dnf", "yum", "zypper")):
        return "rpm"
    if shutil.which("apt-get"):
        return "deb"
    if shutil.which("rpm"):
        return "rpm"
    if shutil.which("dpkg"):
        return "deb"
    return None
