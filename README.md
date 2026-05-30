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

## How it works
- agy OAuth lives in the **system keyring** (`service=gemini, user=antigravity`).
  Account snapshots saved to `~/.gemini/accounts/<email>.json`.
- Model+effort is a single string in `~/.gemini/antigravity-cli/settings.json`.
- Quota errors (`RESOURCE_EXHAUSTED`, `quota reached`, `code 429`, etc.) trigger account rotation. Note: bare `429` is intentionally excluded from the pattern to avoid false positives on Go log timestamps (e.g. `18:40:55.429005`).
- `do-escalate` climbs Flash → Pro → Opus when `AGYKIT_VERIFY` fails.
