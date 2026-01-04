#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get version from pyproject.toml
VERSION=$(grep "version = " pyproject.toml | cut -d'"' -f2)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE} whatbroke v${VERSION} Package Builder${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Clean previous builds
echo -e "${YELLOW}Cleaning previous builds...${NC}"
rm -rf "$BUILD_DIR" "$DIST_DIR" *.egg-info
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# Step 1: Build Python packages first
echo -e "${YELLOW}Step 1: Building Python packages...${NC}"
cd "$PROJECT_DIR"

# Create setup.py for building
cat > setup.py << 'EOF'
#!/usr/bin/env python3

import os
import sys
from setuptools import setup, find_packages

# Read version from pyproject.toml
version = "0.1.0"
try:
    with open("pyproject.toml") as f:
        for line in f:
            if line.strip().startswith("version = "):
                version = line.split('"')[1]
                break
except:
    pass

# Read long description from README
long_description = ""
try:
    with open("README.md") as f:
        long_description = f.read()
except:
    pass

setup(
    name="whatbroke",
    version=version,
    description="Linux system diagnostics tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Emerson",
    author_email="emerson@example.com",
    url="https://github.com/emerson/whatbroke",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: System :: Monitoring",
        "Topic :: System :: Systems Administration",
    ],
    python_requires=">=3.8",
    packages=find_packages(),
    py_modules=["cli", "result"],
    entry_points={
        "console_scripts": [
            "whatbroke=cli:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
EOF

# Skip Python wheel build if setuptools not available, focus on native packages
if python3 -c "import setuptools" 2>/dev/null; then
    python3 setup.py bdist_wheel
    echo -e "${GREEN}✓ Python wheel package created${NC}"
else
    echo -e "${YELLOW}Python build tools not available, focusing on native packages...${NC}"
fi

# Step 2: Create source tarball for native packages
echo -e "${YELLOW}Step 2: Creating source tarball for native packages...${NC}"
cd "$PROJECT_DIR"
tar -czf "$DIST_DIR/whatbroke-$VERSION.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='packaging' \
    *.py pyproject.toml *.md *.txt checks/ 2>/dev/null || true

# Step 3: Build .deb package
echo -e "${YELLOW}Step 3: Building .deb package...${NC}"
if command -v dpkg-deb &> /dev/null; then
    echo -e "${GREEN}dpkg-deb found, building .deb package...${NC}"
    
    # Create temporary debian directory structure
    DEB_BUILD="$BUILD_DIR/debian"
    mkdir -p "$DEB_BUILD/DEBIAN"
    mkdir -p "$DEB_BUILD/usr/bin"
    mkdir -p "$DEB_BUILD/usr/share/doc/whatbroke"
    mkdir -p "$DEB_BUILD/usr/lib/python3/dist-packages/whatbroke"
    mkdir -p "$DEB_BUILD/usr/lib/python3/dist-packages/whatbroke/checks"
    
    # Create control file
    cat > "$DEB_BUILD/DEBIAN/control" << EOF
Package: whatbroke
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Depends: python3
Maintainer: Emerson <emerson@example.com>
Description: Linux system diagnostics tool
 whatbroke is a CLI tool that performs comprehensive system health checks
 including disk usage, Docker status, hardware metrics, log analysis,
 networking connectivity, and systemd service status. It provides clear
 status reporting with color-coded output and remediation suggestions.
EOF

    # Install files manually
    cd "$PROJECT_DIR"
    mkdir -p "$DEB_BUILD/usr/lib/python3/dist-packages/whatbroke"
    
    # Copy Python files
    cp *.py "$DEB_BUILD/usr/lib/python3/dist-packages/whatbroke/" 2>/dev/null || true
    cp -r checks "$DEB_BUILD/usr/lib/python3/dist-packages/whatbroke/" 2>/dev/null || true
    
    # Create executable
    cat > "$DEB_BUILD/usr/bin/whatbroke" << 'EOF'
#!/usr/bin/env python3
import sys
import os

# Add the library directory to Python path
lib_dir = "/usr/lib/python3/dist-packages/whatbroke"
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from cli import main

if __name__ == "__main__":
    main()
EOF
    
    chmod +x "$DEB_BUILD/usr/bin/whatbroke"
    
    # Move files to correct locations
    if [ -d "$DEB_BUILD/usr/local/lib/python3.*/dist-packages" ]; then
        mv "$DEB_BUILD/usr/local/lib/python3.*/dist-packages/whatbroke"* "$DEB_BUILD/usr/lib/python3/dist-packages/" 2>/dev/null || true
    fi
    if [ -f "$DEB_BUILD/usr/local/bin/whatbroke" ]; then
        mv "$DEB_BUILD/usr/local/bin/whatbroke" "$DEB_BUILD/usr/bin/" 2>/dev/null || true
    fi
    
    # Copy documentation
    cp README.md "$DEB_BUILD/usr/share/doc/whatbroke/" 2>/dev/null || true
    
    # Clean up empty directories
    rm -rf "$DEB_BUILD/usr/local"
    find "$DEB_BUILD" -type d -empty -delete 2>/dev/null || true
    
    # Set proper permissions
    find "$DEB_BUILD" -type d -exec chmod 755 {} \; 2>/dev/null || true
    find "$DEB_BUILD" -type f -exec chmod 644 {} \; 2>/dev/null || true
    chmod 755 "$DEB_BUILD/usr/bin/whatbroke" 2>/dev/null || true
    
    # Build the .deb package
    cd "$BUILD_DIR"
    dpkg-deb --build debian "$DIST_DIR/whatbroke_${VERSION}_all.deb"
    
    echo -e "${GREEN}✓ .deb package created: $DIST_DIR/whatbroke_${VERSION}_all.deb${NC}"
else
    echo -e "${RED}dpkg-deb not found, skipping .deb package${NC}"
    echo -e "${YELLOW}Install with: sudo apt-get install dpkg-dev${NC}"
fi

# Step 4: Build .rpm package
echo -e "${YELLOW}Step 4: Building .rpm package...${NC}"
if command -v rpmbuild &> /dev/null; then
    echo -e "${GREEN}rpmbuild found, building .rpm package...${NC}"
    
    # Setup rpmbuild environment
    mkdir -p "$HOME/rpmbuild/SOURCES" "$HOME/rpmbuild/SPECS" "$HOME/rpmbuild/RPMS/noarch"
    cp "$DIST_DIR/whatbroke-$VERSION.tar.gz" "$HOME/rpmbuild/SOURCES/"
    
    # Create spec file
    cat > "$HOME/rpmbuild/SPECS/whatbroke.spec" << EOF
Name:           whatbroke
Version:        $VERSION
Release:        1%{?dist}
Summary:        Linux system diagnostics tool

License:        MIT
URL:            https://github.com/emerson/whatbroke
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools

Requires:       python3

%description
whatbroke is a CLI tool that performs comprehensive system health checks
including disk usage, Docker status, hardware metrics, log analysis,
networking connectivity, and systemd service status. It provides clear
status reporting with color-coded output and remediation suggestions.

%prep
%autosetup

%build
%{__python3} setup.py build

%install
%{__python3} setup.py install --root=%{buildroot} --optimize=1 --no-compile

%files
%license LICENSE 2>/dev/null || echo "%doc README.md"
%doc README.md
%{python3_sitelib}/whatbroke*
%{python3_sitelib}/whatbroke-%{version}-py*.egg-info
%{_bindir}/whatbroke

%changelog
* $(date +"%a %b %d %Y") Emerson <emerson@example.com> - $VERSION-1
- Initial release of whatbroke Linux system diagnostics tool
- Comprehensive system health checks
- Color-coded output with JSON support
- Docker, systemd, hardware, networking, and log analysis
EOF
    
    # Build the RPM
    cd "$HOME/rpmbuild/SPECS"
    rpmbuild -ba whatbroke.spec 2>/dev/null || rpmbuild -bb whatbroke.spec
    
    # Copy the built RPM to dist directory
    find "$HOME/rpmbuild/RPMS" -name "whatbroke-*.noarch.rpm" -exec cp {} "$DIST_DIR/" \;
    
    echo -e "${GREEN}✓ .rpm package created in $DIST_DIR/${NC}"
else
    echo -e "${RED}rpmbuild not found, skipping .rpm package${NC}"
    echo -e "${YELLOW}Install with: sudo yum install rpm-build or sudo dnf install rpm-build${NC}"
fi

# Step 5: Create package-based installation script
echo -e "${YELLOW}Step 5: Creating package-based installation script...${NC}"
cat > "$DIST_DIR/install.sh" << 'EOF'
#!/bin/bash

# whatbroke package-based installation script
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}whatbroke Package Installer${NC}"
echo -e "${BLUE}=========================${NC}"
echo ""

# Detect available packages
DEB_PACKAGE="$(find "$SCRIPT_DIR" -name "whatbroke_*.deb" | head -1)"
RPM_PACKAGE="$(find "$SCRIPT_DIR" -name "whatbroke-*.rpm" | head -1)"

if [ -z "$DEB_PACKAGE" ] && [ -z "$RPM_PACKAGE" ]; then
    echo -e "${RED}Error: No packages found in $SCRIPT_DIR${NC}"
    echo -e "${YELLOW}Please run the build script first to create packages.${NC}"
    exit 1
fi

# Detect package manager and install
if [ -f "$DEB_PACKAGE" ] && command -v dpkg &> /dev/null; then
    echo -e "${GREEN}Found .deb package and dpkg available${NC}"
    echo -e "${YELLOW}Installing: $DEB_PACKAGE${NC}"
    
    if [ "$EUID" -eq 0 ]; then
        # Root user
        dpkg -i "$DEB_PACKAGE"
        # Fix any missing dependencies
        apt-get install -f -y 2>/dev/null || true
    else
        echo -e "${RED}Root privileges required for package installation${NC}"
        echo -e "${YELLOW}Please run: sudo $0${NC}"
        exit 1
    fi
    
elif [ -f "$RPM_PACKAGE" ] && command -v rpm &> /dev/null; then
    echo -e "${GREEN}Found .rpm package and rpm available${NC}"
    echo -e "${YELLOW}Installing: $RPM_PACKAGE${NC}"
    
    if [ "$EUID" -eq 0 ]; then
        # Root user
        rpm -i "$RPM_PACKAGE"
    else
        echo -e "${RED}Root privileges required for package installation${NC}"
        echo -e "${YELLOW}Please run: sudo $0${NC}"
        exit 1
    fi
    
else
    echo -e "${RED}Error: No compatible package manager found${NC}"
    echo -e "${YELLOW}Available packages:${NC}"
    [ -f "$DEB_PACKAGE" ] && echo -e "  - $(basename "$DEB_PACKAGE")"
    [ -f "$RPM_PACKAGE" ] && echo -e "  - $(basename "$RPM_PACKAGE")"
    echo -e "${YELLOW}Required package manager not found:${NC}"
    [ -f "$DEB_PACKAGE" ] && echo -e "  - dpkg (for .deb packages)"
    [ -f "$RPM_PACKAGE" ] && echo -e "  - rpm (for .rpm packages)"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Installation complete!${NC}"
echo -e "${YELLOW}Run: whatbroke --help${NC}"
EOF

chmod +x "$DIST_DIR/install.sh"

# Step 6: Create uninstall script
echo -e "${YELLOW}Step 6: Creating uninstall script...${NC}"
cat > "$DIST_DIR/uninstall.sh" << 'EOF'
#!/bin/bash

# whatbroke uninstallation script
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}whatbroke Uninstaller${NC}"
echo -e "${BLUE}===================${NC}"
echo ""

# Check if installed via package manager
if command -v dpkg &> /dev/null && dpkg -l | grep -q "whatbroke"; then
    echo -e "${GREEN}Found whatbroke installed via dpkg${NC}"
    echo -e "${YELLOW}Removing whatbroke package...${NC}"
    
    if [ "$EUID" -eq 0 ]; then
        dpkg -r whatbroke 2>/dev/null || dpkg --purge whatbroke
    else
        echo -e "${RED}Root privileges required for package removal${NC}"
        echo -e "${YELLOW}Please run: sudo $0${NC}"
        exit 1
    fi
    
elif command -v rpm &> /dev/null && rpm -q whatbroke &>/dev/null; then
    echo -e "${GREEN}Found whatbroke installed via rpm${NC}"
    echo -e "${YELLOW}Removing whatbroke package...${NC}"
    
    if [ "$EUID" -eq 0 ]; then
        rpm -e whatbroke
    else
        echo -e "${RED}Root privileges required for package removal${NC}"
        echo -e "${YELLOW}Please run: sudo $0${NC}"
        exit 1
    fi
    
else
    echo -e "${RED}whatbroke not found installed via package manager${NC}"
    echo -e "${YELLOW}Checking for manual installation...${NC}"
    
    # Check for manual installation
    MANUAL_LOCATIONS=(
        "/usr/local/bin/whatbroke"
        "/usr/bin/whatbroke"
        "$HOME/.local/bin/whatbroke"
    )
    
    FOUND_MANUAL=false
    for location in "${MANUAL_LOCATIONS[@]}"; do
        if [ -f "$location" ]; then
            echo -e "${YELLOW}Found manual installation at: $location${NC}"
            FOUND_MANUAL=true
        fi
    done
    
    if [ "$FOUND_MANUAL" = true ]; then
        echo -e "${YELLOW}Manual installations must be removed manually:${NC}"
        echo -e "  sudo rm /usr/local/bin/whatbroke"
        echo -e "  sudo rm /usr/bin/whatbroke"
        echo -e "  rm $HOME/.local/bin/whatbroke"
        echo -e "  sudo rm -rf /usr/local/lib/whatbroke"
        echo -e "  sudo rm -rf /usr/lib/python3/dist-packages/whatbroke"
    else
        echo -e "${YELLOW}whatbroke not found on system${NC}"
    fi
    
    exit 0
fi

echo ""
echo -e "${GREEN}✓ Uninstallation complete!${NC}"
echo -e "${YELLOW}Run 'which whatbroke' to verify removal${NC}"
EOF

chmod +x "$DIST_DIR/uninstall.sh"

# Clean up build artifacts
cd "$PROJECT_DIR"
rm -f setup.py
rm -rf "$BUILD_DIR"

# Final summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}🎉 Build Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}Created packages:${NC}"
ls -la "$DIST_DIR"/*.deb "$DIST_DIR"/*.rpm 2>/dev/null || ls -la "$DIST_DIR"

echo ""
echo -e "${GREEN}Installation commands:${NC}"
echo -e "  Package-based: ${YELLOW}sudo $DIST_DIR/install.sh${NC}"
echo -e "  Uninstall:    ${YELLOW}sudo $DIST_DIR/uninstall.sh${NC}"
echo ""
if [ -f "$DIST_DIR/whatbroke_${VERSION}_all.deb" ]; then
    echo -e "${YELLOW}  .deb package available for: ${GREEN}sudo dpkg -i $DIST_DIR/whatbroke_${VERSION}_all.deb${NC}"
fi
if [ -f "$DIST_DIR/whatbroke-$VERSION-1.noarch.rpm" ]; then
    echo -e "${YELLOW}  .rpm package available for: ${GREEN}sudo rpm -i $DIST_DIR/whatbroke-$VERSION-1.noarch.rpm${NC}"
fi

echo ""
echo -e "${GREEN}Test the installation:${NC}"
echo -e "  ${YELLOW}whatbroke --help${NC}"
echo -e "  ${YELLOW}whatbroke --only disk,hardware${NC}"

# Test the locally built version if it exists
if command -v "$PROJECT_DIR/cli.py" &> /dev/null || [ -f "$PROJECT_DIR/cli.py" ]; then
    echo ""
    echo -e "${YELLOW}Quick test of built version:${NC}"
    python3 "$PROJECT_DIR/cli.py" --help | head -3
fi