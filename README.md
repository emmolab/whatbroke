# 🎯 whatbroke

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   __          ___           _   ____            _                            ║
║   \ \        / / |         | | |  _ \          | |                           ║
║    \ \  /\  / /| |__   __ _| |_| |_) |_ __ ___ | | _____                     ║
║     \ \/  \/ / | '_ \ / _` | __|  _ <| '__/ _ \| |/ / _ \                    ║
║      \  /\  /  | | | | (_| | |_| |_) | | | (_) |   <  __/                    ║
║       \/  \/   |_| |_|\__,_|\__|____/|_|  \___/|_|\_\___|                    ║
║                                                                              ║
║                    Find what's broken.   Fix what matters.                   ║
║                                                                              ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

```

 **Linux system diagnostics tool** that performs health checks across 8 critical system categories with monitoring, reporting, and remediation steps.

---

## 🚀 Quick Start

### Installation

**Package-based (recommended):**
```bash
./build-packages.sh
./dist/install.sh
```

**Development mode:**
```bash
git clone https://github.com/emerson/whatbroke.git
cd whatbroke
pip install -e .
```

**Uninstall:**
```bash
sudo ./dist/uninstall.sh
```

---

## 💫 Features Overview

### 📊 **Comprehensive System Monitoring**

| Category | Checks Performed | Status Indicators |
|----------|------------------|-------------------|
| 🗂️ **Disk & Filesystems** | Usage, inodes, RAID/LVM/ZFS, SMART health, network drives | >80% WARN, >90% CRIT |
| 🔥 **Hardware & Performance** | CPU load, memory, swap, temperatures, battery/UPS | CPU >70% WARN, Memory <20% WARN |
| ⚙️ **System Services & Processes** | Systemd services, zombies, high CPU/memory processes, critical services, port conflicts | Any failed = CRIT |
| 🐳 **Containers & Virtualization** | Docker status, exited/restarting containers, Kubernetes, VMs | Any exited = WARN |
| 🌐 **Networking** | Internet connectivity, DNS resolution, firewall, open ports | Failures = WARN |
| 📝 **Logs** | System logs, kernel errors, application logs | Errors detected = WARN |
| 🔒 **Security & Integrity** | Failed logins, security updates, SSH config, certificates | Vulnerabilities = CRIT |
| ⏰ **Scheduled Tasks** | Cron jobs, systemd timers, service status | Failures = WARN |

---

##  Output Formats & Options

### 🎯 **Basic Usage**
```bash
# Run all checks with beautiful ASCII header and colors
whatbroke

# Focus on specific areas
whatbroke --only disk,hardware,security

# Skip noisy checks
whatbroke --skip docker,security
```

### 🔍 **Detailed Monitoring**
```bash
# Verbose output with remediation steps and enhanced details
whatbroke --verbose
```

### 📊 **Automation Ready**
```bash
# JSON output for CI/CD and monitoring systems
whatbroke --json

# Compact output for logging and alerting
whatbroke --compact

# No colors for log files and terminals without color support
whatbroke --no-color
```

### 🔧 **Power User Combinations**
```bash
# Focus on specific areas with JSON output
whatbroke --only disk,hardware --json

# Verbose security audit without colors
whatbroke --only security --verbose --no-color

# Quick health check for monitoring
whatbroke --compact --only critical
```

---

##  Verbose Output Examples

### 🐳 **Container Diagnostics**
```
containers: WARN - Docker containers OK, K8s OK, VMs OK
  • Docker: Running
  • Docker: Found 2 exited container(s)
  •   → test-exited (f0d98859a788): Exited (0) 2 minutes ago [image: alpine]
  •   → old-app (0cd3d3bea240): Exited (143) 5 weeks ago [image: app:v1.2]
  • Docker: Found 1 restarting container(s)
  •   → api-server (3150265e183a): Restarting (1) Less than a second ago (restarts: 4) [image: api:latest]
  • Kubernetes: Tools not available
  → Fix: Clean up exited containers: docker rm <container> || docker system prune
```

### ⏰ **Scheduled Tasks Status**
```
scheduled: OK - Cron service running, 2 user crontabs, 10 systemd timers
  • User crontabs found: emerson, backup
  • Cron service: Active and running
  • Systemd timers: 10 active timers found
```

### 🔒 **Security Health Report**
```
security: OK - Security checks passed
  • Recent authentication logs: No failures detected
  • System packages: All up to date
  • SSH: Root login disabled
  • SSH: Password authentication disabled (key-based only)
  • Firewall: UFW active and configured
  • Certificates: 15 certificates found, all valid
```

### 📈 **Performance Monitoring**
```
hardware: OK - Load: 1.56 (8 CPUs), Memory: 58.0% available, Max temp: 43.0°C
  • CPU load 1.56 (8 cores)
  • Memory available 58.0%
  • Temperatures OK (max: 43.0°C)
  • Swap usage: 2% (healthy)
```

---

##  Status Indicators

| Status | Color | Meaning | Action Required |
|--------|-------|---------|----------------|
| **OK** | 🟢 Green | System healthy | No action needed |
| **WARN** | 🟡 Yellow | Attention needed | Monitor closely |
| **BROKE** | 🔴 Red | Service degraded | Immediate attention |
| **CRIT** | 🟣 Magenta | Critical failure | Urgent action required |

---

## 📋 Command Reference

### Options
- `--help` - Show help message and exit
- `--compact` - Minimal output for logging and alerts
- `-v, --verbose` - Detailed information with remediation steps
- `--only CHECK1,CHECK2` - Run only specified checks
- `--skip CHECK1,CHECK2` - Skip specified checks
- `--json` - Machine-readable JSON output
- `--no-color` - Disable colored output

### Available Checks
- `disk` - Disk usage and filesystem health
- `hardware` - CPU, memory, temperature, performance
- `logs` - System and application logs
- `networking` - Network connectivity and services
- `scheduled` - Cron jobs and systemd timers
- `security` - Security posture and vulnerabilities
- `services` - System services and process health
- `systemd` - Systemd service status
- `docker` - Container and virtualization status

---

## 🔧 Integration & Automation

### JSON Output Structure
```json
[
  {
    "name": "security",
    "status": "OK",
    "message": "Security checks passed",
    "details": [
      "Recent authentication logs: No failures detected",
      "System packages: All up to date",
      "Certificates: 15 certificates found, all valid"
    ],
    "remediation": null
  }
]
```

### Exit Codes
```bash
# Monitor with systemd
whatbroke --compact && echo "System healthy" || echo "System needs attention"

# Use in CI/CD pipelines
whatbroke --only security --json | jq '.[] | select(.status != "OK")'

# Alert integration
if whatbroke --compact | grep -q "WARN\|CRIT\|BROKE"; then
    send-alert.sh "System issues detected"
fi
```

### Cron Integration
```bash
# /etc/cron.d/whatbroke-check
# Check system health every hour
0 * * * * root /usr/local/bin/whatbroke --compact --only critical || logger "System health check failed"
```

---

## 🛠️ Development

### Setup Development Environment
```bash
git clone https://github.com/emerson/whatbroke.git
cd whatbroke
python -m venv venv
source venv/bin/activate
pip install -e .
```

### Testing
```bash
# Test individual checks
PYTHONPATH=. python3 -m whatbroke.cli --only disk,security --verbose

# Test with different output formats
PYTHONPATH=. python3 -m whatbroke.cli --json
PYTHONPATH=. python3 -m whatbroke.cli --compact
PYTHONPATH=. python3 -m whatbroke.cli --no-color
```

### Building Packages
```bash
./build-packages.sh
# Creates packages in ./dist/ directory
# Supports .deb (Debian/Ubuntu) and .rpm (RHEL/Fedora)
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all existing tests pass
5. Submit a pull request

---

## 📊 System Requirements

### Supported Platforms
- **Linux**: All major distributions (Ubuntu, Debian, RHEL, CentOS, Fedora, Arch, etc.)
- **Python**: 3.8+ (required)
- **Permissions**: Standard user (some checks may need sudo for full details)

### Optional Dependencies
- `docker` - For container monitoring
- `kubectl` - For Kubernetes cluster monitoring  
- `ufw` / `firewalld` - For firewall status
- `smartmontools` - For disk SMART monitoring
- `lm-sensors` - For temperature monitoring

---

## 🤝 Support & Contributing

### Getting Help
- 🐛 **Issues**: [GitHub Issues](https://github.com/emerson/whatbroke/issues)

### Contributing Guidelines
- 🎯 Focus on system reliability and actionable insights
- 🔍 Ensure backward compatibility
- 📝 Add comprehensive tests
- 🎨 Maintain consistent code style
- 📚 Update documentation for new features

---

## 📜 License

GNU License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

Built with ❤️ for Linux system administrators, DevOps engineers, and SRE teams who need reliable, actionable system health monitoring.

---

**whatbroke**