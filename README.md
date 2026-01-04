# whatbroke

Linux system diagnostics CLI tool that performs comprehensive health checks including disk usage, Docker status, hardware metrics, log analysis, networking connectivity, and systemd service status.

## Quick Start

### Build Packages
```bash
./build-packages.sh
```

### Install

**Package-based (recommended):**
```bash
./dist/install.sh
```

This script automatically detects your system and installs the appropriate package (.deb for Debian/Ubuntu, .rpm for RHEL/Fedora).

**Uninstall:**
```bash
sudo ./dist/uninstall.sh
```

### Usage
```bash
whatbroke --help
whatbroke --only disk,hardware
whatbroke --json --verbose
```

## Features

- **Disk Usage**: Monitors root filesystem usage
- **Docker**: Checks Docker daemon and exited containers
- **Hardware**: Monitors CPU load and memory usage
- **Logs**: Scans journal for critical errors
- **Networking**: Tests network connectivity and DNS
- **Systemd**: Checks for failed services

## Development

1. Edit code
2. Run `./build-packages.sh`
3. Test installation
4. Commit and tag release

## Output Format

- **OK**: System healthy (green)
- **WARN**: Warning state (yellow)  
- **BROKE**: Critical issue (red)

Use `--json` for machine-readable output and `--verbose` for detailed information and remediation suggestions.