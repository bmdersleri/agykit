# agykit — Portable Antigravity (agy) CLI Manager

Orchestrator-agnostic agy management: works with Claude Code, OpenCode, Codex, or standalone.

Multi-account rotation with quota-aware sorting, model ladder escalation with error context
pass-through, usage dashboard, caveman-style terse output for token savings.

## Install
```bash
git clone https://github.com/bmdersleri/agykit.git
cd agykit && ./install.sh
```
`install.sh` checks deps (agy, python3, git, jq, python-keyring), symlinks to `~/.local/bin`, then checks for an active agy OAuth token. If found, auto-saves an account snapshot. If not, prints numbered next steps.

- Custom prefix: `AGYKIT_PREFIX=/usr/local/bin ./install.sh`
- Uninstall: `./uninstall.sh` (keeps account snapshots + project config)
- Manual: `ln -sf "$PWD/agykit" ~/.local/bin/agykit`

After install, run `agykit doctor` to verify everything is set up correctly.

**Claude Code skill (optional):** install `skills/agykit.md` so Claude Code knows how to use agykit:
```bash
cp "$(dirname $(which agykit))/../skills/agykit.md" ~/.claude/skills/agykit.md
```

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
agykit init                    Interactive project setup in current directory
agykit doctor                  Check installation and system file dependencies
agykit doctor --fix            Auto-fix resolvable issues (quota cache, account snapshot)
```

## Dashboard (`agykit dash`)

Live localhost web dashboard at `http://127.0.0.1:8787` (light/dark theme):

- **agy Account Quota** — per-account cards with Gmail profile photo, model quota bars (from `agy /usage` via tmux), reset times, exhaustion status and countdown
- **Claude Code Quota** — session (5h) + weekly tiers via Anthropic OAuth API
- **Usage Charts** — daily token consumption and model distribution (Chart.js)
- **agy Status** — statusline snapshot + last session summary

Requires `tmux` for model quota capture. First load takes ~30s; results cached for 5 minutes.

## Quota CLI (`agykit quota`)

```bash
agykit quota              # colored table from 5-min cache (instant after first run)
agykit quota --refresh    # force live fetch from agy
agykit quota --status     # "✓ 8 models available" — suitable for shell prompts
agykit quota --json | jq  # pipe to any tool
```

The quota cache (`~/.gemini/antigravity-cli/quota-cache.json`) is also read by the dashboard and the statusline badge.

## Project Setup (new project)

Run in your project directory:

```bash
cd /your/project
agykit init
```

`agykit init` auto-detects your project type (Python/Node/Rust/Go/Justfile), prompts for verify command, source directory, and terse level, then creates:
- `.agykit.conf` — project config (added to `.gitignore` automatically)
- `CLAUDE_AGY_SYSTEM.md` — system context template (edit to describe your project)

Then verify setup:

```bash
agykit doctor        # check all dependencies and data sources
agykit doctor --fix  # auto-fix any resolvable warnings
agykit run "hello"   # smoke test
```

### Manual config reference

<details>
<summary>`.agykit.conf` key settings</summary>

```bash
# Verify command: runs after every code task (required for do-escalate)
AGYKIT_VERIFY="pytest -q"          # Python
# AGYKIT_VERIFY="npm test"         # Node / AGYKIT_VERIFY="cargo test"  # Rust

# System context file injected into every agy prompt
AGYKIT_SYSTEM="CLAUDE_AGY_SYSTEM.md"

# IMPORTANT: point to source directory, NOT $PWD
# $PWD loads logs/lock files/build artifacts → wastes tokens
AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"
# Single-dir: --add-dir $PWD/mypackage   Monorepo: --add-dir $PWD/src --add-dir $PWD/lib

AGYKIT_TIMEOUT="15m"
AGYKIT_TERSE="ultra"   # token savings: lite | full | ultra
```
</details>

---

## Config reference
Per-project `.agykit.conf` (in CWD) or `AGYKIT_*` env vars:
- `AGYKIT_VERIFY` — command run after a code task (needed for `do-escalate`)
- `AGYKIT_SYSTEM` — path to system-context file injected into prompts
- `AGYKIT_FLAGS` — extra agy flags (default: `--dangerously-skip-permissions`)
- `AGYKIT_TIMEOUT` — agy print timeout (default: `15m`)
- `AGYKIT_TERSE` — terse output for `run`: `0`/`lite`/`full`/`ultra` (saves output tokens; default `ultra`)

See `agykit.conf.example` for a full annotated template.

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

## Using agykit from Claude Code

The recommended workflow: use Claude Code for planning, navigation, and context — delegate actual coding tasks to agy via agykit so quota is spread across multiple Google accounts and models.

### When to use which

| Task | Tool |
|------|------|
| Understand codebase, read files, plan | Claude Code directly |
| Write/edit code, fix bugs, refactor | `agykit run` or `agykit do-escalate` via `! agykit ...` |
| One-shot coding task, outcome verified | `agykit do-escalate` |
| Quick rewrite, no verify step needed | `agykit run` |

### Running agykit from within Claude Code

Type `! agykit run "..."` in the Claude Code prompt — the `!` prefix runs the command in your session and its output lands directly in the conversation.

```
! agykit run "refactor the _apply_range function in dashboard/collectors/_common.py to be more readable"

! agykit do-escalate "add pagination to the /api/ops-log endpoint"

! agykit run "write a docstring for every public function in dashboard/alerts.py"
```

### Workflow pattern

1. **You** describe what needs to change to Claude Code  
2. **Claude Code** reads the relevant files and gives you the exact prompt to pass to agy  
3. **You** run `! agykit do-escalate "<that prompt>"` — agy implements, verify runs, quota rotates automatically  
4. **Claude Code** reviews the result

### Effective prompt patterns for `agykit run`

```bash
# Scoped: always name the file and function
! agykit run "in dashboard/collectors/rtk.py, add error handling for when 'rtk gain' returns empty output"

# With context: paste the error inline
! agykit run "fix the TypeError on line 42 of tests/test_alerts.py: 'NoneType' object is not iterable"

# Refactor with constraint
! agykit run "extract the cooldown check in dashboard/alerts.py into a private _is_cooled_down(key, state, now, cooldown) function — no logic changes"
```

### `do-escalate` vs `run`

Use **`do-escalate`** when you have a `AGYKIT_VERIFY` command set (e.g. `pytest -q`). It:
- Runs Flash first (cheapest), escalates to Pro → Opus only on verify failure
- Passes the previous error to the next model as context
- Rolls back agy's git changes on failure — your WIP is always safe

Use **`run`** for tasks with no automated verify (docs, comments, scripts).

### Quota tips

- Check quota before a big task: `! agykit quota --status`
- Add multiple Google accounts with `agykit account-add` to extend capacity
- Dashboard at `http://localhost:8787` shows live quota bars + alert thresholds
- Set `AGYKIT_QUOTA_ALERT_PCT=20` in `.agykit.conf` to get warned earlier

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
