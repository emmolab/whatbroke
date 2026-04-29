#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
step() { echo -e "\n${BLUE}▶${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="${DIST_DIR:-$REPO_DIR/dist}"
BUILD_DIR="${BUILD_DIR:-$REPO_DIR/.build-tmp}"
PKG_NAME="whatbroke"
PY_PKG_DIR="$REPO_DIR/whatbroke"

version() {
    python3 - <<'PY'
import pathlib, tomllib
pyproject = pathlib.Path("pyproject.toml")
print(tomllib.loads(pyproject.read_text())["project"]["version"])
PY
}

VERSION="$(cd "$REPO_DIR" && version)"

cleanup() {
    rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

stage_python_package() {
    local dest="$1"
    mkdir -p "$dest"
    cp -a "$PY_PKG_DIR" "$dest/"
    find "$dest" -type d -name '__pycache__' -prune -exec rm -rf {} +
    find "$dest" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
}

python_sitearch() {
    python3 - <<'PY'
import sysconfig
path = sysconfig.get_path('purelib')
if path.startswith('/usr/local/'):
    path = path.replace('/usr/local/', '/usr/', 1)
print(path)
PY
}

write_entrypoint() {
    local path="$1"
    mkdir -p "$(dirname "$path")"
    cat > "$path" <<'EOF'
#!/usr/bin/python3
from whatbroke.cli import main
main()
EOF
    chmod 0755 "$path"
}

build_python_artifacts() {
    step "Building source + wheel artifacts"
    python3 -m build --sdist --wheel --outdir "$DIST_DIR"
    ok "Python artifacts written to $DIST_DIR"
}

build_deb() {
    if ! command -v dpkg-deb >/dev/null 2>&1; then
        warn "dpkg-deb not found; skipping .deb build"
        return 0
    fi

    step "Building .deb package"
    local root="$BUILD_DIR/deb-root"
    local pyroot="$root/usr/lib/python3/dist-packages"
    mkdir -p "$root/DEBIAN" "$root/usr/share/doc/$PKG_NAME"

    cat > "$root/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.10)
Maintainer: Emerson <emerson@example.com>
Homepage: https://github.com/emmolab/whatbroke
Description: Linux system diagnostics tool for sysadmins
 whatbroke runs parallel health checks across disk, hardware, services,
 logs, networking, security, users, timers, containers, firewall, and mail.
 It sorts findings by severity, supports JSON/compact output, and is designed
 for conservative Linux diagnostics rather than noisy alert spam.
EOF

    stage_python_package "$pyroot"
    write_entrypoint "$root/usr/bin/whatbroke"
    cp "$REPO_DIR/README.md" "$root/usr/share/doc/$PKG_NAME/README.md"
    cp "$REPO_DIR/LICENSE" "$root/usr/share/doc/$PKG_NAME/copyright"

    find "$root" -type d -exec chmod 0755 {} +
    find "$root" -type f ! -path '*/usr/bin/whatbroke' -exec chmod 0644 {} +
    chmod 0755 "$root/usr/bin/whatbroke"

    local deb="$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
    dpkg-deb --build "$root" "$deb" >/dev/null
    ok "Built $(basename "$deb")"
}

build_rpm() {
    if ! command -v rpmbuild >/dev/null 2>&1; then
        warn "rpmbuild not found; skipping .rpm build"
        return 0
    fi

    step "Building .rpm package"
    local topdir="$BUILD_DIR/rpm"
    local sourcedir="$topdir/SOURCES"
    local tarroot="$BUILD_DIR/${PKG_NAME}-${VERSION}"
    mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} "$tarroot"

    stage_python_package "$tarroot"
    cp "$REPO_DIR/README.md" "$REPO_DIR/LICENSE" "$tarroot/"
    cat > "$tarroot/${PKG_NAME}.sh" <<'EOF'
#!/usr/bin/python3
from whatbroke.cli import main
main()
EOF
    chmod 0755 "$tarroot/${PKG_NAME}.sh"

    (cd "$BUILD_DIR" && tar -czf "$sourcedir/${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}")

    local sitearch
    sitearch="$(python_sitearch)"

    cat > "$topdir/SPECS/${PKG_NAME}.spec" <<EOF
Name:           $PKG_NAME
Version:        $VERSION
Release:        1%{?dist}
Summary:        Linux system diagnostics tool for sysadmins
License:        MIT
URL:            https://github.com/emmolab/whatbroke
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       /usr/bin/python3

%description
whatbroke runs parallel health checks across disk, hardware, services,
logs, networking, security, users, timers, containers, firewall, and mail.
It sorts findings by severity and is intended for practical Linux diagnostics.

%prep
%setup -q

%build

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}${sitearch}/whatbroke
cp -a whatbroke/. %{buildroot}${sitearch}/whatbroke/
install -m 0755 ${PKG_NAME}.sh %{buildroot}%{_bindir}/${PKG_NAME}

%files
%license LICENSE
%doc README.md
%{_bindir}/${PKG_NAME}
${sitearch}/whatbroke
%exclude ${sitearch}/whatbroke/__pycache__
%exclude ${sitearch}/whatbroke/__pycache__/*
%exclude ${sitearch}/whatbroke/checks/__pycache__
%exclude ${sitearch}/whatbroke/checks/__pycache__/*

%changelog
* $(LC_ALL=C date '+%a %b %d %Y') Emerson <emerson@example.com> - ${VERSION}-1
- Automated release packaging
EOF

    rpmbuild -bb --define "_topdir $topdir" "$topdir/SPECS/${PKG_NAME}.spec" >/dev/null
    local rpm
    rpm="$(find "$topdir/RPMS" -name '*.rpm' | head -1)"
    cp "$rpm" "$DIST_DIR/"
    ok "Built $(basename "$rpm")"
}

main() {
    step "Preparing dist directory"
    rm -rf "$DIST_DIR" "$BUILD_DIR"
    mkdir -p "$DIST_DIR" "$BUILD_DIR"

    step "Checking prerequisites"
    command -v python3 >/dev/null 2>&1 || { err 'python3 is required'; exit 1; }
    python3 -m build --version >/dev/null 2>&1 || {
        err "python3 -m build is required. Install with: python3 -m pip install build"
        exit 1
    }
    ok "Version: $VERSION"

    build_python_artifacts
    build_deb
    build_rpm

    step "Build summary"
    ls -lh "$DIST_DIR"
}

main "$@"
