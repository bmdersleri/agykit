# agykit — Portable Antigravity (agy) CLI Manager

Orchestrator-agnostic agy management: works with Claude Code, OpenCode, Codex, or standalone.

Multi-account rotation, model+effort selection, quota-aware running, keyring snapshots,
caveman-style terse output for token savings.

## Install
```bash
git clone https://github.com/bmdersleri/agykit.git
cd agykit && ./install.sh
```
`install.sh` checks deps (agy, python3, git, jq, python-keyring) and symlinks to `~/.local/bin`.
- Custom prefix: `AGYKIT_PREFIX=/usr/local/bin ./install.sh`
- Uninstall: `./uninstall.sh` (keeps account snapshots + project config)
- Manual: `ln -sf "$PWD/agykit" ~/.local/bin/agykit`

Check: `agykit --version`

## Commands
```
agykit whoami                  Show active Google account
agykit models                  List model+effort combos
agykit model [name]            Show / set model+effort
agykit account-list            List saved account snapshots
agykit account-save            Snapshot current keyring login
agykit account-add             Guided: launch agy → login → snapshot
agykit switch <email>          Switch to a saved account
agykit run "prompt"            Quota-aware run (rotate accounts)
agykit do-escalate "prompt"    Model ladder Flash→Pro→Opus on verify fail
agykit dash [--port N]         Open the usage dashboard (localhost:8787)
agykit quota [--refresh]       Show per-model quota table (5min cache)
agykit quota --json            Machine-readable JSON (pipe to scripts)
agykit quota --status          One-line summary for statusline/scripts
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

**Step 1 — Create `.agykit.conf` in your project root:**

```bash
cp "$(dirname $(which agykit))/../agykit.conf.example" .agykit.conf
# or:
curl -sL https://raw.githubusercontent.com/bmdersleri/agykit/main/agykit.conf.example > .agykit.conf
```

**Step 2 — Edit `.agykit.conf` for your project:**

```bash
# Verify command: runs after every code task (required for do-escalate)
AGYKIT_VERIFY="pytest -q"          # Python
# AGYKIT_VERIFY="npm test"         # Node
# AGYKIT_VERIFY="cargo test"       # Rust
# AGYKIT_VERIFY="just test"        # Justfile

# System context file: injected into every agy prompt (optional but recommended)
AGYKIT_SYSTEM="CLAUDE_AGY_SYSTEM.md"

# IMPORTANT: point to your source directory, NOT $PWD
# $PWD loads everything including logs, lock files, build artifacts → wastes tokens
AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"
# Single-dir projects: --add-dir $PWD/mypackage
# Monorepos:          --add-dir $PWD/src --add-dir $PWD/lib

AGYKIT_TIMEOUT="15m"
AGYKIT_TERSE="ultra"   # token savings: lite | full | ultra
```

**Step 3 — Create `CLAUDE_AGY_SYSTEM.md` (optional but recommended):**

This file is injected as a system prompt prefix into every `agykit run`/`do-escalate` call.
Include: what the project does, hard constraints, file layout, delegation rules for agy.

```bash
cat > CLAUDE_AGY_SYSTEM.md << 'EOF'
# Project Context

<what the project does, 2-3 sentences>

## Hard constraints
- <language/framework version>
- <zero-X-dependency, stdlib-only, etc.>

## Delegation rules (when invoked via agykit do-escalate)
- Follow the given plan exactly. No scope creep.
- Never delete or weaken tests.
- Never run git commands. Leave changes in working tree.
- Only edit: <list the files agy is allowed to touch>
EOF
```

**Step 4 — Add `.agykit.conf` to `.gitignore`:**

```bash
echo ".agykit.conf" >> .gitignore
```

Config contains local paths (`$PWD`) and is user-specific — do not commit it.

**Step 5 — Test:**

```bash
cd /your/project
agykit whoami          # verify active account
agykit run "hello"     # smoke test
```

---

## Config reference
Per-project `.agykit.conf` (in CWD) or `AGYKIT_*` env vars:
- `AGYKIT_VERIFY` — command run after a code task (needed for `do-escalate`)
- `AGYKIT_SYSTEM` — path to system-context file injected into prompts
- `AGYKIT_FLAGS` — extra agy flags (default: `--dangerously-skip-permissions`)
- `AGYKIT_TIMEOUT` — agy print timeout (default: `15m`)
- `AGYKIT_TERSE` — terse output for `run`: `0`/`lite`/`full`/`ultra` (saves output tokens; default `0`)

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

## How it works
- agy OAuth lives in the **system keyring** (`service=gemini, user=antigravity`).
  Account snapshots saved to `~/.gemini/accounts/<email>.json`.
- Model+effort is a single string in `~/.gemini/antigravity-cli/settings.json`.
- Quota errors (`RESOURCE_EXHAUSTED`, `quota reached`, `code 429`, etc.) trigger account rotation. Note: bare `429` is intentionally excluded from the pattern to avoid false positives on Go log timestamps (e.g. `18:40:55.429005`).
- `do-escalate` climbs Flash → Pro → Opus when `AGYKIT_VERIFY` fails.
