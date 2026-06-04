# agykit — Portable Antigravity (agy) CLI Manager

**v1.4.0** · Works with Claude Code, OpenCode, Codex, or standalone shell.

agykit wraps [Antigravity (agy)](https://antigravity.dev) with multi-account quota rotation, model-ladder escalation, a live usage dashboard, and a Python subprocess orchestrator that eliminates silent job hangs.

---

## What It Does

| Problem | agykit solution |
|---|---|
| agy goes silent mid-run, job stays "running" forever | Python orchestrator kills after 120s silence (`AGYKIT_SILENCE_TIMEOUT`) |
| Quota exhausted mid-session | Rotates across saved accounts automatically, available-first |
| Hard coding task needs verify → fallback | `do-escalate`: Flash → Pro → Opus ladder with error context forwarded |
| Quota cache stale near reset | TTL drops from 5min to 60s when reset ≤ 10min away |
| No visibility into background jobs | Job DB + SSE dashboard + `agykit watch/wait/tail` |

---

## Architecture (v1.4.0)

```
agykit (shell entrypoint)
  ├── cmd_run          ──→  dashboard.orchestrator run      (Python)
  ├── cmd_do_escalate  ──→  dashboard.orchestrator escalate (Python)
  └── all other commands stay in shell

dashboard/orchestrator.py
  ├── OrchestratorBase     subprocess streaming, silence detection, ping (15s), job DB events
  ├── RunOrchestrator      account rotation loop, quota detection, cache invalidation
  └── EscalateOrchestrator model ladder, 3-attempt retry with backoff, verify, git rollback

dashboard/  (Flask SSE server + collectors)
  ├── collectors/jobs.py   SQLite job store, PID-aware recovery
  ├── collectors/agy.py    quota cache with dynamic TTL
  └── jobd.py              job daemon (heartbeat every 10s, stale reap every 5min)
```

---

## Install

### Prerequisites

- **agy** — Antigravity CLI, on `$PATH`
- **python 3.11+** — stdlib only, no pip dependencies
- **git** — required for model-ladder rollback safety
- **tmux** — required for live quota capture
- **jq** — required for quota parsing
- **python-keyring** — account snapshot storage (`pip install keyring` or distro package)

### Clone + install

```bash
git clone https://github.com/bmdersleri/agykit.git
cd agykit
./install.sh
```

`install.sh` checks all deps, symlinks `agykit` to `~/.local/bin`, and auto-saves an account snapshot if an active agy OAuth token is detected.

```bash
AGYKIT_PREFIX=/usr/local/bin ./install.sh   # custom install prefix
./uninstall.sh                               # removes binary (keeps snapshots)
ln -sf "$PWD/agykit" ~/.local/bin/agykit     # manual symlink
```

### Update

```bash
agykit update    # git fetch + ff-only pull, prints old → new version
```

### First login

```bash
agy                        # browser OAuth flow
agykit account-save        # snapshot keyring → ~/.gemini/accounts/<email>.json
agykit whoami              # confirm active account
```

### Add more accounts

Each Google account has independent per-model quotas. With 3+ accounts you can sustain long sessions without manual token juggling.

```bash
agykit account-add         # guided: opens agy → OAuth → auto-saves snapshot
agykit account-list        # verify all accounts registered
```

### Verify installation

```bash
agykit doctor              # check all deps and system files
agykit doctor --fix        # auto-fix quota cache, account snapshot issues
```

---

## Setup for a new project

```bash
cd my-project
agykit init                # interactive: sets verify command, system file, source dir
```

This writes `.agykit.conf` (gitignored) and a project-specific system context file (`CLAUDE_AGY_SYSTEM.md`, `CODEX_AGY_SYSTEM.md`, or `OPENCODE_AGY_SYSTEM.md` depending on detected agent).

---

## Usage

### Basic run (quota-aware rotation)

```bash
agykit run "refactor the auth module to use JWT"
```

Flow: sorts accounts available-first → pings each (15s timeout) → runs agy → detects quota in streaming output → rotates to next account → marks job succeeded/failed.

### Model-ladder escalation with verify

```bash
# Requires AGYKIT_VERIFY in .agykit.conf or env
agykit do-escalate "fix the failing tests in auth/"
```

Flow: tries Flash → Pro → Opus (default ladder). Each model attempt:
1. Run agy with task prompt (+ previous error context if escalating)
2. Run `AGYKIT_VERIFY` command
3. Pass → done. Fail → forward error context, rollback git WIP, try next model
4. All models fail → optional architect review (`AGYKIT_ARCHITECT_ESCALATE`)

### Job observability

```bash
agykit jobs                  # recent jobs with status, stage, age
agykit jobs --status failed  # filter by status
agykit jobs --since 24h      # filter by time window
agykit jobs --json           # machine-readable output
agykit watch <job-id>        # live-stream events (TUI or polling fallback)
agykit wait [job-id]         # block until terminal; exit 0=ok 1=fail 2=timeout
agykit tail                  # live-tail all job events (daemon socket)
agykit cancel <job-id>       # cancel a running job
agykit cancel --all          # cancel all in-progress jobs
agykit stats                 # total/by-status/24h summary
agykit job-log <job-id>      # full event history for one job
agykit prune [--older-than N] # remove old jobs (--dry-run to preview)
```

### Dashboard

```bash
agykit dash                         # foreground, localhost:8787
agykit dash --bg                    # background daemon
agykit dash --bg --tailscale        # expose via Tailscale on port 80
agykit dash --stop                  # stop daemon
agykit dash --status                # check daemon status
```

Dashboard shows: active account, model, per-model quota bars, job history, live agy agent state (context usage, subagent count), Codex balance, RTK savings.

### Quota

```bash
agykit quota                 # per-model quota table (5min cache, 60s near reset)
agykit quota --refresh       # force fresh tmux capture
agykit quota --json          # machine-readable
agykit quota --status        # one-line for statusline/scripts
```

### All commands

```
agykit whoami                  Show active Google account
agykit status                  One-line: account | model | quota summary
agykit models                  List model+effort combos
agykit model [name]            Show / set model+effort
agykit account-list            List saved account snapshots
agykit account-save            Snapshot current keyring login
agykit account-add             Guided: launch agy → login → snapshot
agykit account-remove <email>  Remove a saved account snapshot
agykit switch <email>          Switch to a saved account
agykit run "prompt"            Quota-aware run (available accounts first)
agykit do-escalate "prompt"    Model ladder Flash→Pro→Opus with verify
agykit tasks "prompt"          Structured task queue (from file or inline)
agykit dash [--port N]         Open usage dashboard (foreground)
agykit dash --bg [--port N]    Start dashboard daemon
agykit dash --stop             Stop dashboard daemon
agykit quota [--refresh]       Per-model quota table
agykit quota --json            Machine-readable quota JSON
agykit quota --status          One-line quota for statusline
agykit codex [--json|--status] Codex account/usage info
agykit rtk [--json]            RTK token savings statistics
agykit jobs [N]                Recent jobs
agykit jobs --status failed    Filter by status
agykit jobs --since 24h        Filter by time range
agykit jobs --json             Machine-readable job output
agykit stats                   Job statistics summary
agykit watch <job-id>          Live-stream job events
agykit wait [job-id]           Block until job ends (exit 0=ok 1=fail 2=timeout)
agykit tail                    Live-tail all job events
agykit cancel <job-id>         Cancel a job
agykit cancel --all            Cancel all in-progress jobs
agykit prune [--older-than N]  Remove old jobs
agykit job-log <job-id>        Full event history for a job
agykit log [N]                 Show last N ops log entries (default: 20)
agykit jobd start|stop|status  Manage job daemon
agykit init                    Interactive project setup
agykit update                  Pull latest version from git remote
agykit doctor                  Check installation and dependencies
agykit doctor --fix            Auto-fix resolvable issues
-v|--version                   Print version
```

---

## Config reference

Per-project `.agykit.conf` in CWD (sourced automatically), or `AGYKIT_*` env vars:

| Variable | Description | Default |
|---|---|---|
| `AGYKIT_VERIFY` | Verify command run after each agy attempt in `do-escalate` | — |
| `AGYKIT_SYSTEM` | Path to system context file injected into all prompts | Auto-detected: `CLAUDE_AGY_SYSTEM.md` / `CODEX_AGY_SYSTEM.md` / `OPENCODE_AGY_SYSTEM.md` |
| `AGYKIT_FLAGS` | Extra agy CLI flags | `--dangerously-skip-permissions` |
| `AGYKIT_TIMEOUT` | agy `--print-timeout` value | `15m` |
| `AGYKIT_SILENCE_TIMEOUT` | Seconds without output before orchestrator kills agy | `120` |
| `AGYKIT_JOB_TIMEOUT` | Hard job ceiling in seconds; reaped + SIGTERM'd if exceeded. Keep ≥ `AGYKIT_TIMEOUT` | `1800` |
| `AGYKIT_TERSE` | Terse output level: `0` / `lite` / `full` / `ultra` | `ultra` |
| `AGYKIT_QUOTA_ALERT_PCT` | Warn when model quota drops below N% | — |
| `AGYKIT_AGENT` | Force agent type: `claude` / `codex` / `opencode` | auto-detected |
| `AGYKIT_ARCHITECT_ESCALATE` | Agent for architect review when ladder exhausted: `auto` / `claude` / `codex` / `opencode` | — |
| `AGYKIT_ARCHITECT_MODEL` | Model for opencode architect (`provider/model`) | — |
| `AGY_BIN` | Path to agy binary | `agy` |

---

## Using from Claude Code

```bash
! agykit run "explain the auth flow"          # analysis — use run
! agykit do-escalate "fix the failing tests"  # code task — use do-escalate
! agykit wait                                 # block until job done
! agykit jobs --json                          # check results
```

Use `run` for read-only analysis and explanation. Use `do-escalate` for code modification tasks that need verification.

**Writing a good `do-escalate` prompt:**
- State the **concrete goal** (not "improve", but "make `pytest tests/auth/` pass")
- Include the **relevant file paths** or directory
- The verify command (from `.agykit.conf`) provides the pass/fail signal — keep it fast and deterministic

---

## Using from OpenCode

```bash
! agykit run "prompt"
! agykit do-escalate "prompt"
```

Add dedicated subagents to `opencode.json`:

```json
"agykit-run": {
  "description": "Run a prompt through agykit with quota-aware account rotation",
  "mode": "subagent",
  "model": "9router/zekiler-bedava"
},
"agykit-escalate": {
  "description": "Escalate a code task through agykit (Flash→Pro→Opus) with verify",
  "mode": "subagent",
  "model": "cc/claude-sonnet-4-6"
}
```

---

## Using from Codex

```bash
agykit run "prompt"
agykit do-escalate "prompt"
```

Codex is auto-detected via `OPENAI_API_KEY` / `CODEX_*` env markers. System context file `CODEX_AGY_SYSTEM.md` is injected if present.

---

## Job lifecycle

```
starting → running → verifying → succeeded
                  ↘ rotating   → running (next account)
                  ↘ failed
                  ↘ blocked    (interrupted via SIGINT/SIGTERM)
                  ↘ timed_out  (AGYKIT_JOB_TIMEOUT exceeded)
```

Jobs are stored in SQLite (`~/.local/share/agykit/jobs.db` or `AGYKIT_STATE_DIR`). The job daemon (`jobd`) runs heartbeat recovery every 10s: any job whose owner PID is dead and has had no events for 300s is reaped to `failed`.

The Python orchestrator guarantees a terminal state via `atexit` — even if the shell is killed, the daemon catches it within the next heartbeat cycle.

---

## System file dependencies

| Path | Purpose |
|---|---|
| `~/.gemini/accounts/<email>.json` | Saved account snapshots |
| `~/.gemini/antigravity-cli/settings.json` | Active model + account |
| `~/.gemini/antigravity-cli/quota-cache.json` | Quota cache (dynamic TTL) |
| `~/.local/share/agykit/jobs.db` | Job SQLite store |
| `/tmp/agykit-out.log` | Last agy stdout (transient) |
| `/tmp/agykit-verify.log` | Last verify command output (transient) |
| `.agykit.conf` | Per-project config (gitignored) |

---

## How it works (internals)

**Silence detection** — `run_agy()` streams `agy` stdout line-by-line. If no output arrives within `AGYKIT_SILENCE_TIMEOUT` (default 120s), the subprocess is killed and the result is treated as a transient error. PID liveness is irrelevant.

**Account ordering** — Currently-active account first (respects manual `agykit switch`), then remaining accounts by quota status (available before exhausted).

**Dynamic quota TTL** — `agy_model_quota_cached()` uses a 300s TTL normally. When the account's reset time is ≤ 10 minutes away, TTL drops to 60s. When `run_agy()` detects a quota hit in streaming output, it immediately invalidates the cache.

**Git rollback** — `do-escalate` takes a `git stash` snapshot before each agy attempt. On quota hit or verify failure, the snapshot is restored before trying the next model. The baseline commit (`HEAD`) is never touched.

**Architect escalation** — When all ladder models are exhausted and `AGYKIT_ARCHITECT_ESCALATE` is set, the shell passes the original prompt + last verify output + current git diff to the configured architect agent for a root-cause analysis.
