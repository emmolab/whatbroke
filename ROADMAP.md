# whatbroke roadmap ideas

This is a product-direction backlog for turning `whatbroke` from a great one-shot CLI into a small operating surface for Linux health triage.

The core principle should stay the same: **conservative, trustworthy findings first**. New UX should make those findings easier to run continuously, review historically, and act on safely without turning `whatbroke` into a noisy monitoring suite.

## 1. Lightweight web GUI

A web UI would make `whatbroke` easier to use on servers where admins want a quick health page instead of SSHing in and reading terminal output.

Good first version:

- local-only by default, binding to `127.0.0.1`
- read-only dashboard backed by the same check engine as the CLI
- status cards sorted by severity: `CRIT`, `BROKE`, `WARN`, then `OK`
- detail drawer for each check with message, evidence, and remediation
- last-run timestamp, duration, host metadata, and exit severity
- “broken only” toggle matching `whatbroke --broken-only`
- JSON endpoint for wrappers: `/api/v1/results`

Security defaults:

- no remote bind unless explicitly requested
- optional reverse-proxy friendly mode for Caddy/Nginx/Traefik
- no shell command execution from the browser in v1
- redact sensitive evidence before display where checks include paths, usernames, or logs

Implementation path:

1. add `whatbroke --serve [--host 127.0.0.1] [--port 8765]`
2. use Python stdlib HTTP first, or a tiny optional dependency only if the UI needs it
3. render a static HTML/CSS/JS dashboard from the latest run payload
4. keep the API schema stable so future integrations do not scrape pretty text

## 2. Better daemon / agent mode

A daemon would let `whatbroke` run continuously without cron glue and would make state transitions more useful.

Good first version:

- `whatbroke daemon` runs checks on an interval and stores the latest result set
- systemd unit and timer examples for packaged installs
- jittered intervals to avoid every host checking at the same second
- single-instance lock to avoid overlapping runs
- health endpoint for the web UI and external monitors
- configurable output sinks: local state file, webhook, syslog, and compact stdout

Suggested CLI shape:

```bash
whatbroke daemon --interval 5m
whatbroke daemon --interval 1m --only disk,services,networking
whatbroke daemon --webhook https://example.com/whatbroke --diff-only
```

Important behavior:

- alert only on new, worsened, changed, or recovered broken checks by default
- keep the daemon quiet when nothing changed
- preserve the current CLI exit-code semantics for one-shot runs
- avoid requiring root; checks should continue to degrade gracefully and explain when sudo would improve confidence

## 3. Historical timeline

The current state file already tracks transitions. A small history layer would make it much easier to answer “when did this start?”

Potential features:

- append-only event log for changes: new, worse, changed, improved, recovered
- `whatbroke history` command
- web UI timeline per check
- retention policy, e.g. keep 30 days by default
- export as JSON Lines for ingestion elsewhere

Example:

```bash
whatbroke history --since 24h
whatbroke history --check services --json
```

## 4. Alerting integrations

Once daemon mode exists, add simple sinks that do not require a full monitoring stack.

Useful targets:

- generic webhook
- Discord/Slack-compatible webhook payloads
- email via local sendmail when present
- syslog / journald structured messages
- ntfy or Gotify for self-hosted push alerts

Guardrails:

- default to diff-only alerts
- include exact remediation hints and evidence snippets
- include hostname and check name in every alert
- rate-limit repeated noisy checks

## 5. Fleet-friendly collector mode

A later step could support multiple machines without becoming a heavy platform.

Possible shape:

- each host runs `whatbroke daemon --push https://collector.example/api/v1/hosts/<id>`
- collector stores latest status per host and exposes a simple dashboard
- shared UI shows worst hosts first
- no agent remote-control in early versions; collect status only

## Recommended sequencing

1. **Stable JSON result schema** — make it explicit and documented.
2. **Daemon mode** — interval runner, single-instance lock, quiet diff-only behavior.
3. **Local web GUI** — reads daemon/latest-run data and exposes a safe local dashboard.
4. **History** — append-only transitions and retention.
5. **Alert sinks** — webhook/syslog/email with rate-limiting.
6. **Fleet collector** — optional, only after single-host UX is solid.

This keeps `whatbroke` useful as a small sysadmin tool while opening a path toward a web GUI and always-on companion daemon.
