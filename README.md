# agykit — Portable Antigravity (agy) CLI Manager

Orchestrator-agnostic agy management: works with Claude Code, OpenCode, Codex, or standalone.

Multi-account rotation with quota-aware sorting, model ladder escalation with error context
pass-through, usage dashboard, caveman-style terse output for token savings.

---

## Install

### Prerequisites

- **agy** — Antigravity CLI (must be installed and on `$PATH`)
- **python 3.11+** — stdlib only, no pip dependencies
- **git** — required for model-ladder rollback
- **tmux** — required for live quota capture
- **jq** — required for quota parsing
- **python-keyring** — for account snapshot storage (`pip install keyring` or distro package)

### Clone + install

```bash
git clone https://github.com/bmdersleri/agykit.git
cd agykit
./install.sh
```

`install.sh` checks all deps, symlinks the `agykit` binary to `~/.local/bin`, and auto-saves an account snapshot if an active agy OAuth token is detected.

Options:

```bash
AGYKIT_PREFIX=/usr/local/bin ./install.sh   # custom install prefix
./uninstall.sh                               # removes binary (keeps snapshots + project config)
ln -sf "$PWD/agykit" ~/.local/bin/agykit     # manual symlink
```

### First login — agy OAuth + account-save

If you have not logged in to agy yet:

```bash
agy                        # launches browser OAuth flow
agykit account-save        # snapshot keyring → ~/.gemini/accounts/<email>.json
agykit whoami              # confirm active account
```

### Add more accounts (why it matters)

Each Google account has independent per-model quotas. agykit rotates across all saved accounts before hitting a hard wall. Add every Google account you own:

```bash
agykit account-add         # guided: opens agy → OAuth login → auto-saves snapshot
agykit account-list        # verify all accounts are registered
```

With 3+ accounts you can sustain long coding sessions without manual token juggling.

### Install agent skills (auto on `./install.sh`)

The installer detects which coding agents you use and installs the matching skill files:

| Agent | Files | Install path |
|-------|-------|-------------|
| Claude Code | `skills/agykit.md` | `~/.claude/skills/agykit.md` |
| Codex | `skills/codex.md` | `~/.codex/skills/agykit.md` |
| OpenCode | `skills/SKILL.md`, `.opencode/plugins/agykit/`, `.opencode/commands/agykit.md` | `~/.agents/skills/agykit/`, `~/.config/opencode/plugins/agykit/` |

Manual install:

```bash
# Claude Code
cp "$(dirname $(which agykit))/../skills/agykit.md" ~/.claude/skills/agykit.md

# Codex
cp "$(dirname $(which agykit))/../skills/codex.md" ~/.codex/skills/agykit.md

# OpenCode (skill + plugin)
cp "$(dirname $(which agykit))/../skills/SKILL.md" ~/.agents/skills/agykit/SKILL.md
mkdir -p ~/.config/opencode/plugins/agykit
cp "$(dirname $(which agykit))/../.opencode/plugins/agykit/plugin.js" ~/.config/opencode/plugins/agykit/
cp "$(dirname $(which agykit))/../.opencode/plugins/agykit/package.json" ~/.config/opencode/plugins/agykit/
```

### Verify installation

```bash
agykit doctor              # checks all deps, data sources, account snapshots
agykit doctor --fix        # auto-fixes resolvable warnings (cache, snapshots)
```

---

## Setup for a new project

### Step-by-step

1. Change to your project directory and run init:

   ```bash
   cd /your/project
   agykit init
   ```

   `agykit init` auto-detects your project type (Python / Node / Rust / Go / Justfile), prompts for verify command, source directory, and terse level, then creates:
   - `.agykit.conf` — project config (added to `.gitignore` automatically)
   - `CLAUDE_AGY_SYSTEM.md` — system context template

2. Edit `CLAUDE_AGY_SYSTEM.md` with your project's context — architecture summary, key files, conventions, what agy should and should not touch. The more specific, the better the results.

3. Set `AGYKIT_VERIFY` to your test command in `.agykit.conf`:

   ```bash
   AGYKIT_VERIFY="pytest -q"       # Python
   # AGYKIT_VERIFY="npm test"      # Node
   # AGYKIT_VERIFY="cargo test"    # Rust
   # AGYKIT_VERIFY="just check"    # Justfile
   ```

   `do-escalate` will not escalate without this set.

4. Point `AGYKIT_FLAGS` to your source directory — **not `$PWD`**:

   ```bash
   # Good: scope to source only
   AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"

   # Bad: $PWD loads logs, lock files, build artifacts → wastes tokens
   # AGYKIT_FLAGS="--add-dir $PWD --dangerously-skip-permissions"
   ```

   Monorepo example:
   ```bash
   AGYKIT_FLAGS="--add-dir $PWD/src --add-dir $PWD/lib --dangerously-skip-permissions"
   ```

5. Smoke test:

   ```bash
   agykit run "hello"             # should respond via agy, no errors
   agykit doctor                  # all green
   ```

---

## Commands

```
agykit whoami                  Show active Google account
agykit status                  One-line: active account | model | quota summary
agykit models                  List model+effort combos
agykit model [name]            Show / set model+effort
agykit account-list            List saved account snapshots
agykit account-save            Snapshot current keyring login
agykit account-add             Guided: launch agy → login → snapshot
agykit account-remove <email>  Remove a saved account snapshot
agykit switch <email>          Switch to a saved account
agykit run "prompt"            Quota-aware run (available accounts first)
agykit do-escalate "prompt"    Model ladder Flash→Pro→Opus, verify error passed forward
agykit dash [--port N]         Open the usage dashboard (localhost:8787)
agykit quota [--refresh]       Show per-model quota table (5min cache)
agykit quota --json            Machine-readable JSON (pipe to scripts)
agykit quota --status          One-line summary for statusline/scripts
agykit codex                   Show Codex account & usage information
agykit codex --json            Machine-readable Codex JSON output
agykit codex --status          One-line Codex summary for statusline
agykit rtk                     Show RTK token savings statistics
agykit rtk --json              Machine-readable RTK JSON output
agykit init                    Interactive project setup (agent-aware system file)
agykit doctor                  Check installation and system file dependencies
agykit doctor --fix            Auto-fix resolvable issues (quota cache, account snapshot)
agykit log [N]                 Show last N ops log entries (default: 20)
agykit jobs [N]                Show N most recent jobs (default: 20)
agykit jobs --status failed    Filter jobs by status
agykit jobs --since 24h        Filter jobs by time range
agykit jobs --json             Machine-readable JSON job output
agykit stats                   Job statistics (total, by status, last 24h)
agykit watch <job-id>          Live-stream a running job (TUI or terminal)
agykit wait [job-id]           Block until a job ends (exit 0=ok 1=fail 2=timeout)
agykit tail                    Live-tail all job events (socket)
agykit cancel <job-id>         Cancel a running/starting job
agykit cancel --all            Cancel all in-progress jobs
agykit prune [--older-than N]  Remove old jobs (N=seconds, or 7d/30d)
agykit job-log <job-id>        Show full event history for a specific job
```

---

## Dashboard (`agykit dash`)

Live localhost web dashboard at `http://127.0.0.1:8787` (light/dark theme):

- **agy Account Quota** — per-account cards with Gmail profile photo, model quota bars (from `agy /usage` via tmux), reset times, exhaustion status and countdown
- **Claude Code Quota** — session (5h) + weekly tiers via Anthropic OAuth API
- **Codex Kullanımı** — sessions, prompts, tokens, recent prompt history
- **Codex Hesap** — account email, plan type, subscription, current model, thread/token totals
- **Usage Charts** — daily token consumption and model distribution (Chart.js)
- **agy Status** — statusline snapshot + last session summary
- **RTK Tasarruf** — token savings statistics from rtk gain
- **Aktif Job** — current running job status, stage, account, model, recent events
- **Aktivite Akışı** — combined feed of recent agy and Claude Code activity
- **Health Center** — local runtime checks for dependencies, config, storage, and agent data sources
- **Job Timeline** — structured lifecycle view for the active or most recent job
- **Recommended Account/Model** — explainable next-run suggestion based on quota, history, and project fit
- **Quota Forecast** — burn-rate-based estimate for quota exhaustion risk and remaining jobs
- **Agent Performance Matrix** — cross-agent comparison for reliability, speed, and token efficiency

Dashboard uses **SSE typed events** — when data changes (quota refresh, new job event,
Codex activity), only the affected card refreshes instead of a full page reload.

Requires `tmux` for model quota capture. First load takes ~30s; results cached for 5 minutes.

For endpoint details and sample data, see [docs/dashboard-api.md](docs/dashboard-api.md),
[docs/dashboard-usage.md](docs/dashboard-usage.md), and
[tests/fixtures/dashboard/README.md](tests/fixtures/dashboard/README.md).

---

## Job Observability

Every `agykit run` and `agykit do-escalate` invocation is recorded as a **job**
with structured events. Jobs are stored in `~/.gemini/agykit-jobs/` as
snapshots (`<job_id>.json`) and append-only event logs (`<job_id>.events.jsonl`).

### CLI commands

```bash
agykit jobs                  # list recent jobs with status, stage, age
agykit jobs --status failed  # filter by status
agykit jobs --since 24h      # filter by time range
agykit jobs --json           # machine-readable output
agykit stats                 # job statistics summary
agykit watch <job-id>        # live-stream (TUI via Textual, polling fallback)
agykit wait [job-id]         # block until terminal; scriptable exit code
agykit tail                  # live-tail all job events (socket)
agykit cancel <job-id>       # cancel a running job
agykit cancel --all          # cancel all in-progress jobs
agykit prune [--older-than N] # remove old jobs (--dry-run to preview)
agykit job-log <job-id>      # full event history for one job
agykit status                # includes active job + codex + rtk info
```

### Dashboard card

The dashboard shows an **Aktif Job** card with current status, stage, account,
model, and the 5 most recent events. It auto-refreshes alongside the existing
SSE refresh cycle.
If `~/.gemini` is not writable in the current environment, agykit copies the
job store to a writable temp directory and keeps using that automatically.

The job timeline is also exposed as JSON at `/api/active-job/timeline` and
`/api/jobs/<job_id>/timeline`. The other dashboard data endpoints are:

- `/api/health`
- `/api/recommendation`
- `/api/quota-forecast`
- `/api/agent-matrix`

See `docs/dashboard-api.md` for the response shapes and field notes.

### Job lifecycle

| Event | Meaning |
|-------|---------|
| `job_started` | Job created, initial snapshot written |
| `account_selected` | Account switch for this attempt |
| `model_selected` | Model/effort set for this escalation step |
| `quota_rotated` | Quota exhausted, rotating to next account |
| `verify_started` | `AGYKIT_VERIFY` command launched |
| `verify_passed` | Verify returned 0 |
| `verify_failed` | Verify returned non-zero |
| `rollback_started` | Git rollback in progress |
| `job_succeeded` | Final success |
| `job_failed` | All accounts or all models exhausted |
| `job_timed_out` | Exceeded `AGYKIT_JOB_TIMEOUT` — reaped (and SIGTERM'd by the daemon) |
| `job_blocked` (stage `recovered`) | Owner process gone while job was active — reaped |

`run` and `do-escalate` are **synchronous**, so the agykit shell that launched
the job is recorded as its `owner_pid`. Recovery uses that PID as ground truth:
a job whose owner is still alive is **never** marked stale, no matter how long
agy works silently; a job whose owner has died is reaped at once instead of
waiting out the 5-minute idle window. The hard `AGYKIT_JOB_TIMEOUT` ceiling
still applies regardless of PID as a runaway backstop.

### Waiting for completion (scripting)

`agykit watch` is an interactive TUI. To gate a script on a job, use `wait`:

```bash
agykit do-escalate "implement X"      # prints "==> job: <id>" up front
agykit wait                           # waits on the most-recent job
echo $?                               # 0 succeeded · 1 failed · 2 wait timed out

agykit wait <job-id> --timeout 1800   # give up after 30 min (exit 2)
```

`wait` is the supported completion signal for orchestrators (CI, Claude Code,
cron) — poll-free and exit-code driven. It runs the same PID-aware recovery each
tick, so a crashed run resolves to `failed` promptly rather than hanging.

### Storage layout

```
~/.gemini/agykit-jobs/
  20260601T120000-a1b2c3.json          # current snapshot
  20260601T120000-a1b2c3.events.jsonl  # append-only event log
```

The legacy `~/.gemini/agykit-ops.log` continues to be written for backward
compatibility.

---

## Quota CLI (`agykit quota`)

```bash
agykit quota              # colored table from 5-min cache (instant after first run)
agykit quota --refresh    # force live fetch from agy
agykit quota --status     # "✓ 8 models available" — suitable for shell prompts
agykit quota --json | jq  # pipe to any tool
```

The quota cache (`~/.gemini/antigravity-cli/quota-cache.json`) is also read by the dashboard and the statusline badge.

---

## Using agykit from Claude Code

The recommended workflow: use Claude Code for planning, navigation, and context — delegate actual implementation to agy via agykit so quota is spread across multiple Google accounts and models.

### The full loop

1. **Describe** what needs to change to Claude Code.
2. **Claude Code** reads the relevant files and produces a scoped, specific prompt.
3. **You** run `! agykit do-escalate "<that prompt>"` — agy implements, verify runs, quota rotates automatically.
4. **Claude Code** reviews the diff and result.

This loop keeps Claude Code's context clean (no large code edits inline) and uses agy quota for the heavy lifting.

### The `!` prefix — running agykit inside Claude Code

Type `! agykit ...` directly in the Claude Code prompt bar. The `!` prefix executes the command in your shell session and pipes its output back into the conversation — you see the result inline without leaving Claude Code.

```
! agykit run "refactor the _apply_range function in dashboard/collectors/_common.py to be more readable"

! agykit do-escalate "add pagination to the /api/ops-log endpoint"

! agykit quota --status
```

### When to use `run` vs `do-escalate`

| Task | Command |
|------|---------|
| Understand codebase, read files, plan | Claude Code directly (no agykit) |
| Docs, comments, scripts — no test needed | `agykit run` |
| Quick rewrite, outcome visible by inspection | `agykit run` |
| Code change + automated test (`AGYKIT_VERIFY` set) | `agykit do-escalate` |
| Bug fix where you need guaranteed green tests | `agykit do-escalate` |

### Writing a good `do-escalate` prompt

A good prompt has four elements:

1. **File + line scope** — name the file and function, not just the feature
2. **What to do** — concrete action verb (add, extract, fix, replace)
3. **Constraints** — what must not change (no logic changes, keep signature, do not rename)
4. **Verify hint** (optional) — what the verify command will check

```bash
# Scoped with constraint
! agykit do-escalate "in dashboard/alerts.py, extract the cooldown check (lines 88-102) into a private _is_cooled_down(key, state, now, cooldown) function — no logic changes, existing tests must pass"

# Bug fix with error inline
! agykit do-escalate "fix TypeError on line 42 of tests/test_alerts.py: 'NoneType' object is not iterable — do not modify the test itself"

# Feature addition with scope
! agykit do-escalate "add a --dry-run flag to agykit account-remove that prints what would be deleted without deleting — update usage string in cmd_account_remove only"
```

Avoid vague prompts like "improve the dashboard" — agy will not know where to look and may touch unrelated files.

## Using agykit from Codex

Codex uses the same `agykit` CLI directly (no `!` prefix needed — Codex runs
shell commands naturally). The `install.sh` installs `skills/codex.md` to
`~/.codex/skills/agykit.md` automatically when Codex is detected.

Typical Codex loop:

```bash
# In Codex conversation:
agykit status
agykit run "explain the quota detection logic"
agykit do-escalate "add retry to agy_quota_status in dashboard/collectors/agy.py"
```

`agykit init` auto-detects Codex and creates `CODEX_AGY_SYSTEM.md` instead of
`CLAUDE_AGY_SYSTEM.md`. Set `AGYKIT_SYSTEM` explicitly to override.

## Using agykit from OpenCode

OpenCode loads the skill from `skills/SKILL.md` (installed automatically to
`~/.agents/skills/agykit/SKILL.md` by `install.sh`).

The installer also copies the **agykit plugin** to
`~/.config/opencode/plugins/agykit/` — this auto-loads a custom `agykit` tool
and lifecycle hooks (quota error detection, agent registration). A slash command
at `.opencode/commands/agykit.md` gives you `/agykit` in the prompt bar.

### OpenCode subagent config

Add these to `opencode.json` under `agent` for dedicated agykit subagents:

```json
"agykit-run": {
  "description": "Run a prompt through agykit with quota-aware account rotation",
  "mode": "subagent",
  "model": "9router/zekiler-bedava"
},
"agykit-escalate": {
  "description": "Escalate a code task through agykit (Flash → Pro → Opus) with verify",
  "mode": "subagent",
  "model": "cc/claude-sonnet-4-6"
}
```

All commands work the same way — use `agykit run` for analysis and
`agykit do-escalate` for code tasks.

### How `do-escalate` escalation works

```
Flash  →  verify  →  pass: done
                  →  fail: error captured
          Pro    →  verify (error from Flash as context)  →  pass: done
                                                           →  fail: error captured
                  Opus  →  verify (errors from Flash+Pro as context)  →  pass: done
                                                                       →  fail: all-exhausted
```

- Each escalation step **passes the previous model's verify error output** as context — Pro and Opus know exactly what went wrong.
- After each step, agykit takes a `git` snapshot. On failure, WIP is rolled back — your working tree is always safe.
- If all three models fail, status is `all-exhausted` and the last error is printed.

### Multi-account quota extension

With multiple accounts saved, agykit sorts them by quota status before every run:
- Available accounts go first.
- Exhausted accounts fall to the end as a fallback (sometimes still work after a short wait).
- Mid-run quota errors trigger automatic rotation to the next account without interrupting the task.

Check how many accounts you have ready:

```bash
agykit account-list
agykit quota --status        # "✓ N models available across M accounts"
```

Add more with `agykit account-add`.

### Quota monitoring tips

```bash
! agykit quota --status      # quick check before a big task
! agykit quota               # full table: per-model limits and resets
```

- Dashboard at `http://localhost:8787` shows live quota bars, per-account cards, and alert thresholds.
- Set `AGYKIT_QUOTA_ALERT_PCT=20` in `.agykit.conf` to be warned when any model drops below 20%.
- First dashboard load takes ~30s (live tmux capture). Subsequent loads use the 5-minute cache.

---

## Config reference

Per-project `.agykit.conf` (in CWD) or `AGYKIT_*` env vars:

| Variable | Description | Default |
|----------|-------------|---------|
| `AGYKIT_VERIFY` | Command run after a code task (needed for `do-escalate`) | — |
| `AGYKIT_SYSTEM` | Path to system-context file injected into prompts | Agent-detected: `CLAUDE_AGY_SYSTEM.md`, `CODEX_AGY_SYSTEM.md`, or `OPENCODE_AGY_SYSTEM.md` (also reads `.opencode/commands/agykit.md`) |
| `AGYKIT_FLAGS` | Extra agy flags | `--dangerously-skip-permissions` |
| `AGYKIT_TIMEOUT` | agy print timeout | `15m` |
| `AGYKIT_JOB_TIMEOUT` | Hard job ceiling (s); past this a job is reaped + SIGTERM'd regardless of PID. `0`/empty disables. Keep **≥ `AGYKIT_TIMEOUT`** or long agy runs get cut mid-flight | `1800` |
| `AGYKIT_TERSE` | Terse output level: `0`/`lite`/`full`/`ultra` | `ultra` |
| `AGYKIT_QUOTA_ALERT_PCT` | Warn when model quota drops below N% | — |
| `AGYKIT_AGENT` | Force orchestrator agent: `claude`/`codex`/`opencode` (else auto-detected) | auto |
| `AGYKIT_ARCHITECT_ESCALATE` | Agent CLI for architect review when ladder fails: `auto`/`claude`/`codex`/`opencode` | — |
| `AGYKIT_ARCHITECT_MODEL` | Model for opencode architect, format `provider/model` | — |

See `agykit.conf.example` for a full annotated template.

### Agent detection priority

agykit auto-detects which agent is running it:

1. `AGYKIT_AGENT` env override (always wins)
2. **Runtime signals** — `CLAUDE_CODE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` → claude · `CODEX_*` → codex · `OPENCODE*` → opencode
3. **On-disk fallback** — `~/.codex/auth.json`, `~/.claude/.credentials.json`, `~/.config/opencode/opencode.json`
4. `unknown`

The detected agent selects the injected system file (`CLAUDE_AGY_SYSTEM.md`, `CODEX_AGY_SYSTEM.md`, or `OPENCODE_AGY_SYSTEM.md`) and routes architect-escalate to the correct non-interactive invocation (`claude -p`, `codex exec`, `opencode run -m`). Run `agykit doctor` → **Agent Integration** panel for a live check.

---

## System File Dependencies

agykit reads files written by **agy** and **Claude Code** — none of these are created manually.
Example copies live in `examples/` for reference.

### agy files (`~/.gemini/`)

| File | Written by | Used for | Missing → |
|------|-----------|----------|-----------|
| `~/.gemini/antigravity-cli/settings.json` | agy | Active model+effort (`agykit model`) | `agykit model` errors |
| `~/.gemini/accounts/<email>.json` | `agykit account-save` | Account rotation, dashboard cards | No accounts to rotate |
| `~/.gemini/antigravity-cli/brain/*/` | agy (per session) | agy usage charts in dashboard | Charts empty |
| `~/.gemini/antigravity-cli/log/cli-*.log` | agy | Quota status, exhaustion tracking | Quota panel empty |
| `~/.gemini/antigravity-cli/statusline-latest.json` | agy statusline hook | "agy Canlı Durum" panel | Panel shows "snapshot yok" |
| `~/.gemini/antigravity-cli/quota-cache.json` | `agykit quota` | Dashboard quota display, 5min cache | Fetched live on demand |

**System keyring** (`service=gemini, user=antigravity`): holds the active OAuth token.
Managed entirely by agy — never edit directly.

### Claude Code files (`~/.claude/`)

| File | Written by | Used for | Missing → |
|------|-----------|----------|-----------|
| `~/.claude/stats-cache.json` | Claude Code (auto) | Claude usage charts in dashboard | Claude charts empty |
| `~/.claude/.credentials.json` | `claude auth login` | Claude Code quota API call | Quota panel shows warning |

### Setup checklist

```bash
# 1. agy: log in and save account snapshot
agy                          # complete OAuth login
agykit account-save          # snapshot keyring → ~/.gemini/accounts/<email>.json

# 2. Claude Code: ensure credentials exist
claude auth login            # writes ~/.claude/.credentials.json

# 3. Verify dashboard data sources
agykit quota                 # populates quota-cache.json
agykit dash                  # open dashboard — check all panels load
```

The `statusline-latest.json` is populated automatically each time agy renders its statusline.
Configure it via `agy`'s settings or the `statusline.sh` hook in `~/.gemini/antigravity-cli/`.

### Example file formats

See `examples/` for annotated JSON skeletons of each file:

```
examples/
  agy-settings.json.example          ~/.gemini/antigravity-cli/settings.json
  agy-account-snapshot.json.example  ~/.gemini/accounts/<email>.json
  agy-statusline-latest.json.example ~/.gemini/antigravity-cli/statusline-latest.json
  agy-quota-cache.json.example       ~/.gemini/antigravity-cli/quota-cache.json
  claude-credentials.json.example    ~/.claude/.credentials.json
  claude-stats-cache.json.example    ~/.claude/stats-cache.json
```

---

## How it works

**Account rotation (`run` / `do-escalate`)**
Before each run, accounts are sorted by quota status (reads agy CLI logs): available accounts are tried first, exhausted ones fall to the end as a fallback. On a quota error mid-run, agykit rotates to the next account automatically.

**Model escalation (`do-escalate`)**
Climbs Flash → Pro → Opus when `AGYKIT_VERIFY` fails. Each escalation passes the previous model's verify error output as context to the next model — so Pro/Opus know exactly what failed and why, rather than starting blind.

**Quota detection**
Errors matching `RESOURCE_EXHAUSTED`, `quota reached`, `rate limit`, `code 429`, etc. trigger rotation. Bare `429` is intentionally excluded to avoid false positives on Go log timestamps (e.g. `18:40:55.429005`).

**Authentication**
agy OAuth lives in the **system keyring** (`service=gemini, user=antigravity`). Account snapshots saved to `~/.gemini/accounts/<email>.json`. Model+effort is a single string in `~/.gemini/antigravity-cli/settings.json`.
