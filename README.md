# whatbroke

```text
 __          ___           _   ____            _
 \ \        / / |         | | |  _ \          | |
  \ \  /\  / /| |__   __ _| |_| |_) |_ __ ___ | | _____
   \ \/  \/ / | '_ \ / _` | __|  _ <| '__/ _ \| |/ / _ \
    \  /\  /  | | | | (_| | |_| |_) | | | (_) |   <  __/
     \/  \/   |_| |_|\__,_|\__|____/|_|  \___/|_|\_\___|

 Find what's broken. Fix what matters.
```

Linux system diagnostics tool for sysadmins. Runs 12 health checks in parallel, sorts results by severity, and aims for conservative, trustworthy findings instead of noisy red ink.

---

## Quick Start

**Install or upgrade from the latest GitHub Release (recommended):**
```bash
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash
```

The installer detects Debian/RPM family hosts using `/etc/os-release` and the active package manager, so mixed-tool systems do not get misclassified just because `dpkg` happens to exist.

**Uninstall:**
```bash
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/uninstall.sh | bash
```

The installer:
- detects whether the host uses `dpkg`/APT or `rpm`/DNF/YUM/Zypper
- downloads the matching `.deb` or `.rpm` from the latest GitHub Release
- installs it, or upgrades an existing installation in place

The uninstaller:
- removes `whatbroke` via `dpkg`, `rpm`, `python3 -m pip`, `pip3`, or `pip` depending on how it was installed
- supports `--purge-state` if you also want to remove root-owned state under `/root/.local/share/whatbroke`
- is safe to re-run if you want a simple removal command for docs or automation

**Install a specific release:**
```bash
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash -s -- --version v0.3.2
```

**Build packages locally:**
```bash
./build-packages.sh
sudo ./dist/install.sh
```

**Run without installing:**
```bash
git clone https://github.com/emmolab/whatbroke.git
cd whatbroke
python3 -m whatbroke
```

That uses the package entrypoint directly, so the source-tree smoke test matches the installed operator workflow.

**pip install (development/local use):**
```bash
pip install -e .
whatbroke
# or, if you prefer the Python module entrypoint
python3 -m whatbroke
```

---

## What it checks

Results are sorted worst-first (CRIT → WARN → OK).

| Check | What it looks at |
|-------|-----------------|
| `disk` | Filesystem usage (>80% WARN, >90% CRIT), inodes, SMART health, RAID/LVM degradation, read-only remounts caused by I/O errors |
| `hardware` | CPU load, memory, swap, temperatures, uptime context |
| `services` | Failed systemd units, stale zombie processes, package manager lock files |
| `logs` | Critical journal entries, repeated error storms, kernel/OOM events |
| `networking` | Default route, gateway reachability, DNS sanity, outbound HTTPS, NTP sync, NIC errors and drops |
| `security` | Failed SSH logins, update backlog context, SSH policy, locally-managed cert expiry, Let's Encrypt/certbot renewal state, explicit reboot-required signals, SELinux/AppArmor, entropy pool |
| `sysctl` | Kernel hardening parameters (ASLR, syncookies, ICMP redirects, plus contextual values like rp_filter and kptr_restrict) |
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

# See the exact check names you can use with --only/--skip
whatbroke --list-checks

# Add one-line descriptions when choosing a focused run
whatbroke --list-checks -v

# Remove the package and root-owned state (if present)
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/uninstall.sh | bash -s -- --purge-state
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
# Only show broken checks that are NEW, worse, or otherwise changed since the last run
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
*/15 * * * * root whatbroke --compact --diff | mail -s "whatbroke: new issues on $(hostname)" root@localhost
```

Because `--diff` outputs nothing when there are no changed broken checks, this only sends mail when a problem appears or materially changes.

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

`whatbroke` writes per-check state to `~/.local/share/whatbroke/state.json` after each run. This powers two features:

- **Change badges** — checks can be tagged `[NEW]`, `[WORSE]`, `[CHANGED]`, `[IMPROVED]`, or `[RECOVERED]`
- **`--diff` mode** — only shows broken checks that are new or changed since the previous run; prints `No broken checks changed since last run.` otherwise

The pretty view adds a short `Next:` hint for non-OK results so an on-call admin gets an immediate fix prompt without needing full verbose mode.

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
  --diff             Show only broken checks that changed since last run
  --no-state         Don't read or write the state file
  --list-checks      List available check names and exit (add -v for descriptions)
  --version          Print version and exit
```

---

## Output example

```
disk:      CRIT  2 full drives  [NEW]
  ↳ Next: Free space on the affected filesystem.
logs:      CRIT  54 critical journal entries, 50 kernel issues  [WORSE]
  ↳ Next: Review the top noisy unit and recent critical journal lines.
scheduled: CRIT  cron service down
  ↳ Next: Restart cron and inspect why it stopped.
networking: WARN  2 NIC error(s)
  ↳ Next: review this check before it escalates.
services:  WARN  3 stale zombie(s)
sysctl:    WARN  2 sysctl misconfiguration(s)
containers: OK   All container/virtualisation checks passed
firewall:  OK    Firewall active
hardware:  OK    Hardware healthy — Load 1.2/8, Mem 60% free, Swap 2%, Temp 42°C
mail:      OK    No MTA detected — mail checks skipped
security:  OK    Security checks passed
users:     OK    User accounts look clean (37 total, 1 login)

Overall: CRIT  3 CRIT  1 BROKE  3 WARN  12 checks  0.6s  21:23:59  changed since last run: 1 new  1 worse
```

---

## Releases, packaging, and upgrades

### What gets published

Create a GitHub Release from a version tag and GitHub will automatically provide the source archive (`.tar.gz` and `.zip`) for that tag. The included Actions workflow then builds and uploads these additional release assets:

- `whatbroke-<version>.tar.gz` (sdist)
- `whatbroke-<version>-py3-none-any.whl`
- `whatbroke_<version>_all.deb`
- `whatbroke-<version>-1.noarch.rpm`
- local helper scripts in `dist/` (`install.sh`, `uninstall.sh`) when building manually

### Build packages locally

```bash
# Produces ./dist/*.tar.gz, *.whl, *.deb, *.rpm (where toolchain is available)
./build-packages.sh

# Install the local build on this host
sudo ./dist/install.sh

# Remove a local dpkg/rpm installation
sudo ./dist/uninstall.sh
```

Requirements for local package building:
- Python artifacts: `python3 -m build` (`python3 -m pip install build`)
- `.deb`: `dpkg-deb` (`apt install dpkg-dev` or equivalent)
- `.rpm`: `rpmbuild` (`dnf install rpm-build` / `apt install rpm` or equivalent)

### Release a new version

The release flow is now **tag-driven** instead of “publish a release first, then refresh its assets”.

1. land the feature/fix work on `main`
2. prepare the version bump + annotated tag locally
3. push `main` with `--follow-tags`
4. let GitHub Actions build and publish the artifacts for that tag

```bash
# Example: cut v0.4.0
./scripts/prepare-release.sh 0.4.0
git push origin main --follow-tags
```

`./scripts/prepare-release.sh` will:
- validate the requested version
- update `pyproject.toml` and `whatbroke/__init__.py`
- create commit `Release vX.Y.Z`
- create annotated tag `vX.Y.Z`

Pushing that tag triggers `.github/workflows/release.yml`, which:

1. checks out the tagged source
2. verifies the git tag matches `pyproject.toml`
3. builds sdist + wheel + `.deb` + `.rpm`
4. uploads them to the workflow run
5. creates the GitHub Release automatically if needed, or refreshes the assets if it already exists

That means a release page ends up with:
- GitHub's automatic source `.zip` and `.tar.gz`
- built installable packages for Debian-family and RPM-family systems

For this public repo, the release helpers themselves stay committed:
- `scripts/prepare-release.sh`
- `scripts/build-release.sh`
- repo-root `build-packages.sh`, `install.sh`, and `uninstall.sh`

Those are part of the shared source/release workflow and are meant to be reviewed publicly.
Only generated output stays ignored locally, such as `dist/`, `.build-tmp/`, `.pytest_cache/`, `__pycache__/`, coverage output, and `*.egg-info/`.

If you need to rebuild assets for an existing tag without cutting a new version, rerun the workflow manually with `workflow_dispatch` and provide the tag.

### Auto-install / upgrade script

The repo-root `install.sh` is designed to be hosted directly from GitHub and used as either a first install or an upgrade path.

```bash
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash
```

It will:
- detect Linux + package format (`.deb` vs `.rpm`)
- resolve the latest GitHub Release via the GitHub API
- download the matching asset
- install or upgrade with `dpkg -i` or `rpm -Uvh`

Useful flags:

```bash
# Pin a specific tag
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash -s -- --version v0.3.2

# Preview the chosen asset URL only
curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash -s -- --dry-run
```

---

## Requirements

- Python 3.10+
- Designed for Linux servers and headless/admin use cases first
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

## Philosophy

`whatbroke` is intentionally conservative:
- transient noise should stay informational where possible
- repeated or clearly actionable failures should rise to WARN/BROKE/CRIT
- output should help an on-call Linux admin decide what to inspect next

Recent behavior changes in `0.3.2`:
- the runtime banner is now plain and terminal-safe instead of relying on wide ASCII art
- UFW detection behaves more sensibly under both `sudo` and unprivileged runs, distinguishing confirmed active/inactive state from "installed, but needs sudo to confirm"
- package-manager lock checks now focus on active transactions and ignore harmless leftover lock files / stale pid files
- repeated UFW BLOCK / deny spam is suppressed from log alerting so routine firewall noise does not dominate output
- AppArmor "enabled but 0 profiles in enforce mode" is now contextual instead of an automatic warning
- sysctl output focuses on higher-signal server hardening gaps, while more environment-dependent tunables are reported as context
- zombie detection now looks for long-lived zombies using `ps` fields like PID, PPID, STAT, ELAPSED, and COMMAND
- small non-security package backlogs are informational instead of warnings
- security checks now focus certificate scanning on locally managed service certs instead of the whole CA trust store
- Let's Encrypt/certbot state is surfaced more usefully: managed lineage count, earliest expiry context, broken certbot state, and disabled/inactive renewal timers
- explicit reboot-required markers now surface as a warning, so patched hosts awaiting a controlled restart do not look fully green
- scheduled-task detection now ignores disabled/backup cron drop-ins and non-executable run-parts files, reducing cron false positives
- ordinary low-volume journal/kernel noise is de-emphasised; repeated storms and severe events still alert loudly
- hardware thresholds are less jumpy on long-lived servers
- non-OK results now include a terse `Next:` line in the pretty output to make triage faster under pressure
- baseline state now tracks all checks, so `--diff` can surface worsened or otherwise changed failures and the main summary can call out recovered checks

## License

MIT
