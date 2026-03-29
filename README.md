# whatbroke

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   __          ___           _   ____            _                            ║
║   \ \        / / |         | | |  _ \          | |                           ║
║    \ \  /\  / /| |__   __ _| |_| |_) |_ __ ___ | | _____                    ║
║     \ \/  \/ / | '_ \ / _` | __|  _ <| '__/ _ \| |/ / _ \                   ║
║      \  /\  /  | | | | (_| | |_| |_) | | | (_) |   <  __/                   ║
║       \/  \/   |_| |_|\__,_|\__|____/|_|  \___/|_|\_\___|                   ║
║                                                                              ║
║                   Find what's broken.  Fix what matters.                     ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

Linux system diagnostics tool for sysadmins. Runs 12 health checks in parallel, sorts results by severity, and tells you exactly what to fix.

---

## Quick Start

**Install from package (recommended):**
```bash
./build-packages.sh
sudo ./dist/install.sh
```

**Run without installing:**
```bash
git clone https://github.com/emerson/whatbroke.git
cd whatbroke
PYTHONPATH=. python3 -m whatbroke.cli
```

**pip install:**
```bash
pip install -e .
whatbroke
```

---

## What it checks

Results are sorted worst-first (CRIT → WARN → OK).

| Check | What it looks at |
|-------|-----------------|
| `disk` | Filesystem usage (>80% WARN, >90% CRIT), inodes, SMART health, RAID/LVM degradation, read-only remounts caused by I/O errors |
| `hardware` | CPU load, memory, swap, temperatures, uptime (>365 days WARN) |
| `services` | Failed/activating systemd units, zombie processes, package manager lock files |
| `logs` | Critical journal entries, kernel errors, OOM killer events |
| `networking` | Internet/DNS reachability, NTP sync, NIC errors and drops |
| `security` | Failed SSH logins, SELinux/AppArmor status, entropy pool |
| `sysctl` | Kernel hardening parameters (ASLR, syncookies, ICMP redirects, rp_filter, kptr_restrict, etc.) |
| `firewall` | nftables / iptables / ufw / firewalld active status |
| `users` | Extra UID-0 accounts, empty passwords, `NOPASSWD:ALL` sudoers grants |
| `scheduled` | Cron service, systemd timers, recently failed timers |
| `containers` | Docker/Podman exited or crash-looping containers, Kubernetes node status |
| `mail` | MTA service running (postfix/exim/sendmail/opensmtpd), mail queue depth (>50 WARN, >500 CRIT) |

---

## Usage

### Everyday commands

```bash
# Full run — worst problems listed first
whatbroke

# Only show what's broken (hide OK checks)
whatbroke -b

# Verbose — show details and remediation hints for everything
whatbroke -v

# Verbose on broken checks only
whatbroke -b -v

# Focus on specific areas
whatbroke --only disk,security,sysctl
```

### Live dashboard

```bash
# Refresh every 5 seconds (default)
whatbroke --watch

# Refresh every 30 seconds
whatbroke --watch 30

# Watch only broken checks
whatbroke --watch --broken-only
```

### Incident/alerting workflows

```bash
# Only show issues that are NEW since the last run
whatbroke --diff

# Compact one-liner per broken check — good for scripts and cron
whatbroke --compact

# JSON output — pipe into jq, monitoring systems, etc.
whatbroke --json | jq '.[] | select(.status != "OK")'
```

### Suppress output
```bash
# No ANSI colours (log files, terminals without colour support)
whatbroke --no-color

# Skip a noisy check
whatbroke --skip logs,containers

# One-shot run that doesn't touch the state file
whatbroke --no-state
```

---

## Status levels

| Status | Colour | Meaning |
|--------|--------|---------|
| `OK` | Green | Healthy |
| `WARN` | Yellow | Needs attention |
| `BROKE` | Magenta | Degraded / partial failure |
| `CRIT` | Red | Critical — act now |

The overall worst status is used as the **exit code** (0=OK, 1=WARN, 2=BROKE, 3=CRIT), making it easy to integrate into scripts and alerting pipelines.

---

## Automation

### Cron — alert only on new issues
```bash
# /etc/cron.d/whatbroke
# Runs every 15 minutes; emails only when something new breaks
*/15 * * * * root whatbroke --compact --diff | mail -s "whatbroke: new issues on $(hostname)" ops@example.com
```

Because `--diff` outputs nothing when there are no new issues, this only sends mail when a previously-passing check starts failing.

### Monitoring system integration
```bash
# Nagios/Icinga-compatible exit codes
whatbroke --only disk,hardware --compact
echo "Exit: $?"
```

### Pipe into jq
```bash
whatbroke --json | jq '
  .[] | select(.status == "CRIT") | {name, message, remediation}
'
```

### systemd oneshot service
```ini
# /etc/systemd/system/whatbroke.service
[Unit]
Description=whatbroke system health check

[Service]
Type=oneshot
ExecStart=/usr/bin/whatbroke --compact
```

---

## State file

`whatbroke` writes issue state to `~/.local/share/whatbroke/state.json` after each run. This powers two features:

- **`[NEW]` badge** — checks that weren't broken on the previous run are tagged `[NEW]` in the output
- **`--diff` mode** — only shows checks that just became broken; prints "No new issues since last run." otherwise

Use `--no-state` to skip reading/writing the state file entirely.

---

## All options

```
whatbroke [options]

Output:
  (default)          Pretty output, sorted by severity
  -b, --broken-only  Only show non-OK checks
  -v, --verbose      Show details and remediation hints
  --compact          One line per broken check (script-friendly)
  --json             JSON array output
  --no-color         Disable ANSI colours

Filtering:
  --only CHECK,...   Run only these checks (comma-separated)
  --skip CHECK,...   Skip these checks

Behaviour:
  --watch [N]        Live-refresh dashboard every N seconds (default: 5)
  --diff             Show only checks new/newly broken since last run
  --no-state         Don't read or write the state file
  --version          Print version and exit
```

---

## Output example

```
disk:      CRIT  2 full drives  [NEW]
logs:      CRIT  54 critical journal entries, 50 kernel issues
scheduled: CRIT  cron service down
networking: WARN  2 NIC error(s)
services:  WARN  1 zombie(s)
sysctl:    WARN  2 sysctl misconfiguration(s)
containers: OK   All container/virtualisation checks passed
firewall:  OK    Firewall active
hardware:  OK    Hardware healthy — Load 1.2/8, Mem 60% free, Swap 2%, Temp 42°C
mail:      OK    No MTA detected — mail checks skipped
security:  OK    Security checks passed
users:     OK    User accounts look clean (37 total, 1 login)

Overall: CRIT  3 CRIT  3 WARN  12 checks  0.6s  21:23:59  1 new
```

---

## Building packages

```bash
# Produces ./dist/whatbroke-*.whl + .deb + .rpm
./build-packages.sh

# Install on the current host (auto-detects dpkg vs rpm)
sudo ./dist/install.sh

# Uninstall
sudo ./dist/uninstall.sh
```

Requirements for package building:
- `.whl`: `python3 -m build` — `sudo pacman -S python-build` / `pip install build`
- `.deb`: `dpkg-deb` — `sudo pacman -S dpkg` / `sudo apt install dpkg-dev`
- `.rpm`: `rpmbuild` — `sudo pacman -S rpm-tools` / `sudo dnf install rpm-build`

---

## Requirements

- Python 3.10+
- Linux (any distribution)
- No mandatory external dependencies — all checks degrade gracefully when optional tools are absent

**Optional tools** (checks skip cleanly if not present):
- `smartctl` — SMART disk health
- `mdadm` / `vgs` — RAID/LVM status
- `docker` / `kubectl` — container checks
- `nft` / `iptables` / `ufw` / `firewall-cmd` — firewall checks
- `mailq` / `exim` / `smtpctl` — mail queue checks
- `sensors` — CPU/GPU temperature

---

## License

MIT
