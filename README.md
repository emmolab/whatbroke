# 🔧 whatbroke

🧠 **Enterprise-grade Linux system diagnostics tool** that performs comprehensive health checks across 8 categories: Disk & Filesystems, Hardware & Performance, System Services & Processes, Containers & Virtualization, Networking, Logs, Security & Integrity, and Scheduled Tasks.

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

### 🚀 Usage Examples

```bash
# 🎯 Run all checks with colorful output
whatbroke

# 🎯 Run specific checks
whatbroke --only disk,hardware,security

# ⏭ Skip certain checks
whatbroke --skip docker,containers

# 🔍 Verbose output with remediation steps
whatbroke --verbose

# 📄 JSON output for automation
whatbroke --json

# 📱 Compact output for logs
whatbroke --compact

# 🎨 No color output for logs
whatbroke --no-color

# 🔄 Combine all options
whatbroke --only disk,hardware --json --verbose --compact
```

### 🎨 Output Formats

- **🟢 Status Colors**: 🟢 OK | 🟡 WARN | 🔴 BROKEN | 🟣 CRITICAL
- **📄 JSON Mode**: Machine-readable for automation
- **📱 Compact Mode**: Minimal output for logging  
- **🔍 Verbose Mode**: Full details with remediation steps

## Features

**Comprehensive System Monitoring:**

### 1. Disk & Filesystems
- Root filesystem usage (>80% WARN, >90% CRIT)
- Disk inodes usage (>80% WARN, >90% CRIT) 
- Mounted network drives availability
- RAID/LVM/ZFS status checks
- Disk SMART health monitoring

### 2. Hardware & Performance
- CPU load vs core count (>70% per core WARN, >90% CRIT)
- Memory usage (<20% WARN, <10% CRIT)
- Swap usage (>50% WARN, >80% CRIT)
- Temperature sensors (CPU/GPU/HDD >70°C WARN, >85°C CRIT)
- Battery/UPS status monitoring

### 3. System Services & Processes
- Systemd failed services (any CRIT)
- Zombie processes (>0 WARN)
- High CPU/memory process offenders
- Critical services status (DB, web, etc.)
- Port conflict detection

### 4. Containers & Virtualization  
- Docker exited containers (any WARN)
- Restarting containers (>3 restarts WARN)
- Kubernetes node/pod status (any CRIT)
- VM host status monitoring

### 5. Networking
- Internet connectivity (fail WARN)
- DNS resolution (fail WARN) 
- Firewall status (disabled CRIT)
- Open ports/listeners monitoring

### 6. Logs
- System logs (journalctl -p 3..4)
- Kernel errors/warnings (dmesg)
- Application-specific logs (web, DB, etc.)

### 7. Security & Integrity
- Failed login attempts (>3 WARN)
- Outdated security updates (any WARN, critical CRIT)
- SSH configuration (root/password auth enabled WARN)
- Sudoers syntax checks
- Certificate expiration (<30 days WARN)

### 8. Scheduled Tasks
- Cron jobs failing (fail WARN)
- Systemd timers status (fail/inactive CRIT)

## 🎨 Output Colors

- 🟢 **OK**: System healthy (green)
- 🟡 **WARN**: Warning state (yellow)  
- 🔴 **BROKE**: Broken state (red)
- 🟣 **CRIT**: Critical failure (magenta/purple)

## Usage

```bash
# Run all checks
whatbroke

# Run specific checks
whatbroke --only disk,hardware

# Skip certain checks
whatbroke --skip docker,containers

# Verbose output with details
whatbroke --verbose

# JSON output for automation
whatbroke --json

# Combine options
whatbroke --only disk,hardware --json --verbose
```

## Development

1. Edit code
2. Run `./build-packages.sh`
3. Test installation
4. Commit and tag release

Use `--json` for machine-readable output and `--verbose` for detailed information and remediation suggestions.