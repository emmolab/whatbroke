#!/bin/bash
# whatbroke — package builder
# Produces: dist/whatbroke-<ver>-py3-none-any.whl
#           dist/whatbroke_<ver>_all.deb   (if dpkg-deb available)
#           dist/whatbroke-<ver>-1.noarch.rpm  (if rpmbuild available)

set -euo pipefail

# ─── colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
step() { echo -e "\n${BLUE}▶${NC} $*"; }

# ─── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_SRC="$SCRIPT_DIR/whatbroke"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/.build-tmp"

# ─── version ───────────────────────────────────────────────────────────────────
# Parse from pyproject.toml without spawning Python (grep fallback)
if python3 -c "import tomllib" 2>/dev/null; then
    VERSION=$(python3 -c "
import tomllib
with open('$SCRIPT_DIR/pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")
elif python3 -c "import tomli" 2>/dev/null; then
    VERSION=$(python3 -c "
import tomli
with open('$SCRIPT_DIR/pyproject.toml', 'rb') as f:
    print(tomli.load(f)['project']['version'])
")
else
    # Pure grep fallback (no external deps needed)
    VERSION=$(grep '^version' "$SCRIPT_DIR/pyproject.toml" | head -1 | cut -d'"' -f2)
fi

if [[ -z "$VERSION" ]]; then
    err "Could not determine version from pyproject.toml"
    exit 1
fi

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}  whatbroke v${VERSION} — Package Builder  ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"

# ─── sanity checks ─────────────────────────────────────────────────────────────
step "Checking prerequisites"
if [[ ! -d "$PKG_SRC" ]]; then
    err "Source directory not found: $PKG_SRC"
    err "Run this script from the repository root."
    exit 1
fi
python3 --version >/dev/null 2>&1 || { err "python3 not found"; exit 1; }
ok "Source: $PKG_SRC"
ok "Python: $(python3 --version)"

# ─── clean ─────────────────────────────────────────────────────────────────────
step "Cleaning previous build artefacts"
rm -rf "$BUILD_DIR" "$DIST_DIR"
find "$SCRIPT_DIR" -name "*.pyc" -delete
find "$SCRIPT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$BUILD_DIR" "$DIST_DIR"
ok "Clean"

# ─── Python wheel ──────────────────────────────────────────────────────────────
step "Building Python wheel"
WHEEL_FILE=""
if python3 -m build --version >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && python3 -m build --wheel --outdir "$DIST_DIR")
    WHEEL_FILE=$(find "$DIST_DIR" -name "whatbroke-*.whl" | head -1)
elif python3 -c "import setuptools, wheel" 2>/dev/null; then
    (cd "$SCRIPT_DIR" && python3 -m pip wheel --no-deps -w "$DIST_DIR" .)
    WHEEL_FILE=$(find "$DIST_DIR" -name "whatbroke-*.whl" | head -1)
else
    warn "Neither 'build' nor 'wheel' available — skipping wheel"
    warn "Arch/CachyOS: sudo pacman -S python-build"
    warn "Other:        pip3 install build"
fi
[[ -n "$WHEEL_FILE" ]] && ok "Wheel: $(basename "$WHEEL_FILE")"

# ─── helper: stage Python package files ────────────────────────────────────────
# Usage: _stage_pkg <destination_python_root>
# Copies whatbroke/ package tree into <dest>/whatbroke/
_stage_pkg() {
    local dest="$1"
    mkdir -p "$dest/whatbroke/checks"
    cp "$PKG_SRC"/__init__.py   "$dest/whatbroke/"
    cp "$PKG_SRC"/cli.py        "$dest/whatbroke/"
    cp "$PKG_SRC"/result.py     "$dest/whatbroke/"
    cp "$PKG_SRC/checks/"*.py   "$dest/whatbroke/checks/"
}

# ─── helper: create the /usr/bin/whatbroke wrapper ─────────────────────────────
_make_wrapper() {
    local dest="$1"
    mkdir -p "$dest/usr/bin"
    cat > "$dest/usr/bin/whatbroke" << 'WRAPPER'
#!/usr/bin/python3
from whatbroke.cli import main
main()
WRAPPER
    chmod 755 "$dest/usr/bin/whatbroke"
}

# ─── .deb package ──────────────────────────────────────────────────────────────
step "Building .deb package"
if command -v dpkg-deb &>/dev/null; then
    DEB_ROOT="$BUILD_DIR/deb"
    PY3_DIST="$DEB_ROOT/usr/lib/python3/dist-packages"

    # Debian control file
    mkdir -p "$DEB_ROOT/DEBIAN"
    cat > "$DEB_ROOT/DEBIAN/control" << EOF
Package: whatbroke
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Maintainer: Emerson <emerson@example.com>
Description: Linux system diagnostics tool
 whatbroke performs comprehensive health checks across disk, hardware,
 services, networking, security, logs, containers, and scheduled tasks.
 It produces colour-coded output with per-check remediation hints, and
 can emit JSON for use in monitoring pipelines.
 .
 New in 0.2.0: NTP sync check, NIC error detection, OOM event detection,
 SELinux/AppArmor status, entropy pool check, package manager lock
 detection, and proper system-wide severity escalation.
EOF

    # Stage Python package
    _stage_pkg "$PY3_DIST"

    # Wrapper script
    _make_wrapper "$DEB_ROOT"

    # Documentation
    mkdir -p "$DEB_ROOT/usr/share/doc/whatbroke"
    cp "$SCRIPT_DIR/README.md" "$DEB_ROOT/usr/share/doc/whatbroke/" 2>/dev/null || true
    cat > "$DEB_ROOT/usr/share/doc/whatbroke/copyright" << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: whatbroke
Upstream-Contact: emerson@example.com
License: MIT
EOF

    # Permissions
    find "$DEB_ROOT" -type d -exec chmod 755 {} \;
    find "$DEB_ROOT" -type f -exec chmod 644 {} \;
    chmod 755 "$DEB_ROOT/usr/bin/whatbroke"

    # Build
    DEB_FILE="$DIST_DIR/whatbroke_${VERSION}_all.deb"
    dpkg-deb --build "$DEB_ROOT" "$DEB_FILE"
    ok ".deb: $(basename "$DEB_FILE")"
    ok "Install: sudo dpkg -i $DEB_FILE"
else
    warn ".deb skipped — dpkg-deb not found"
    warn "Arch/CachyOS: sudo pacman -S dpkg"
    warn "Debian/Ubuntu: sudo apt-get install dpkg-dev"
fi

# ─── .rpm package ──────────────────────────────────────────────────────────────
step "Building .rpm package"
if command -v rpmbuild &>/dev/null; then
    RPM_TOPDIR="$BUILD_DIR/rpm"
    RPM_DB="$BUILD_DIR/rpmdb"
    RPM_SPEC="$RPM_TOPDIR/SPECS/whatbroke.spec"
    mkdir -p "$RPM_TOPDIR"/{SPECS,SOURCES,BUILD,RPMS,SRPMS}

    # Initialize a local RPM database so rpmbuild works on non-RPM hosts
    # (Arch/CachyOS don't have /var/lib/rpm — no root required for a local db)
    rpm --initdb --dbpath "$RPM_DB" 2>/dev/null || true

    # Source tarball — %prep extracts this; %install copies from it
    TAR_NAME="whatbroke-${VERSION}"
    TAR_DIR="$BUILD_DIR/$TAR_NAME"
    mkdir -p "$TAR_DIR"
    cp -r "$PKG_SRC" "$TAR_DIR/"
    cp "$SCRIPT_DIR/README.md" "$TAR_DIR/" 2>/dev/null || true
    (cd "$BUILD_DIR" && tar -czf "$RPM_TOPDIR/SOURCES/${TAR_NAME}.tar.gz" "$TAR_NAME")

    # Install path: /usr/lib/whatbroke/ avoids Python-version path differences
    # between the build host and the target RPM system.
    CHANGELOG_DATE=$(date +"%a %b %d %Y")
    cat > "$RPM_SPEC" << 'SPEC_EOF'
Name:           whatbroke
SPEC_EOF
    # Append version-dependent lines separately to avoid heredoc quoting issues
    cat >> "$RPM_SPEC" << SPEC
Version:        ${VERSION}
Release:        1
Summary:        Linux system diagnostics — find what's broken, fix what matters

License:        MIT
URL:            https://github.com/emerson/whatbroke
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3 >= 3.8

%description
whatbroke performs comprehensive health checks across disk, hardware,
services, networking, security, logs, containers, and scheduled tasks.
It produces colour-coded output with per-check remediation hints, and
can emit JSON for use in monitoring pipelines or cron jobs.

%prep
%setup -q

%build
# pure Python — nothing to compile

%install
rm -rf %{buildroot}
install -d %{buildroot}/usr/lib/whatbroke/whatbroke/checks
install -d %{buildroot}/usr/bin

cp whatbroke/__init__.py whatbroke/cli.py whatbroke/result.py \\
    %{buildroot}/usr/lib/whatbroke/whatbroke/
cp whatbroke/checks/*.py \\
    %{buildroot}/usr/lib/whatbroke/whatbroke/checks/

cat > %{buildroot}/usr/bin/whatbroke << 'WRAPPER'
#!/usr/bin/python3
import sys
sys.path.insert(0, '/usr/lib/whatbroke')
from whatbroke.cli import main
main()
WRAPPER
chmod 755 %{buildroot}/usr/bin/whatbroke

%files
%doc README.md
/usr/lib/whatbroke/
/usr/bin/whatbroke

%changelog
* ${CHANGELOG_DATE} Emerson <emerson@example.com> - ${VERSION}-1
- v${VERSION}: proper package structure, all imports fixed
- New checks: NTP sync, NIC errors, OOM events, SELinux/AppArmor, entropy
- Replaced netstat with ss; fixed swap usage parsing
SPEC

    rpmbuild -bb \
        --define "_topdir $RPM_TOPDIR" \
        --define "_dbpath $RPM_DB" \
        "$RPM_SPEC" 2>&1 | tail -30

    RPM_FILE=$(find "$RPM_TOPDIR/RPMS" -name "*.rpm" | head -1)
    if [[ -n "$RPM_FILE" ]]; then
        cp "$RPM_FILE" "$DIST_DIR/"
        ok ".rpm: $(basename "$RPM_FILE")"
        ok "Install: sudo rpm -i $DIST_DIR/$(basename "$RPM_FILE")"
    else
        err ".rpm build failed — see rpmbuild output above"
    fi
else
    warn ".rpm skipped — rpmbuild not found"
    warn "Arch/CachyOS: sudo pacman -S rpm-tools"
    warn "RHEL/Fedora:  sudo dnf install rpm-build"
fi

# ─── install / uninstall helpers ───────────────────────────────────────────────
step "Writing install/uninstall helpers"

cat > "$DIST_DIR/install.sh" << 'EOF'
#!/bin/bash
# whatbroke — smart installer (picks .deb or .rpm based on the host)
set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$EUID" -ne 0 ]] && { echo -e "${RED}Run as root: sudo $0${NC}"; exit 1; }

DEB=$(find "$SCRIPT_DIR" -maxdepth 1 -name "whatbroke_*.deb" | head -1)
RPM=$(find "$SCRIPT_DIR" -maxdepth 1 -name "whatbroke-*.rpm" | head -1)

if [[ -n "$DEB" ]] && command -v dpkg &>/dev/null; then
    echo -e "${GREEN}Installing .deb package...${NC}"
    dpkg -i "$DEB"
    apt-get install -f -y 2>/dev/null || true
elif [[ -n "$RPM" ]] && command -v rpm &>/dev/null; then
    echo -e "${GREEN}Installing .rpm package...${NC}"
    rpm -Uvh "$RPM"
else
    echo -e "${RED}No compatible package found in $SCRIPT_DIR${NC}"
    echo -e "${YELLOW}Available: ${DEB:-} ${RPM:-}${NC}"
    exit 1
fi
echo -e "${GREEN}Done! Run: whatbroke --help${NC}"
EOF
chmod +x "$DIST_DIR/install.sh"

cat > "$DIST_DIR/uninstall.sh" << 'EOF'
#!/bin/bash
set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
[[ "$EUID" -ne 0 ]] && { echo -e "${RED}Run as root: sudo $0${NC}"; exit 1; }

if command -v dpkg &>/dev/null && dpkg -l whatbroke &>/dev/null 2>&1; then
    dpkg --purge whatbroke
elif command -v rpm &>/dev/null && rpm -q whatbroke &>/dev/null 2>&1; then
    rpm -e whatbroke
else
    echo -e "${RED}whatbroke not found in dpkg/rpm database${NC}"
    exit 1
fi
echo -e "${GREEN}Uninstalled.${NC}"
EOF
chmod +x "$DIST_DIR/uninstall.sh"

# ─── cleanup ───────────────────────────────────────────────────────────────────
step "Cleaning build temp directory"
rm -rf "$BUILD_DIR"
ok "Done"

# ─── summary ───────────────────────────────────────────────────────────────────
echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}Build complete — whatbroke v${VERSION}${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Artefacts in ./dist/:"
ls -lh "$DIST_DIR/" 2>/dev/null || true
echo ""
echo -e "Quick test (local, no install):"
echo -e "  ${YELLOW}PYTHONPATH=. python3 -m whatbroke.cli --help${NC}"
echo -e "  ${YELLOW}PYTHONPATH=. python3 -m whatbroke.cli --only disk,hardware${NC}"
echo ""
echo -e "Install:"
echo -e "  ${YELLOW}sudo $DIST_DIR/install.sh${NC}"
