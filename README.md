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

## Config
Per-project `.agykit.conf` (in CWD) or `AGYKIT_*` env vars:
- `AGYKIT_VERIFY` — command run after a code task (needed for `do-escalate`)
- `AGYKIT_SYSTEM` — path to system-context file injected into prompts
- `AGYKIT_FLAGS` — extra agy flags (default: `--dangerously-skip-permissions`)
- `AGYKIT_TIMEOUT` — agy print timeout (default: `15m`)
- `AGYKIT_TERSE` — terse output for `run`: `0`/`lite`/`full`/`ultra` (saves output tokens; default `0`)

See `agykit.conf.example`. Copy to your project root as `.agykit.conf`.

## How it works
- agy OAuth lives in the **system keyring** (`service=gemini, user=antigravity`).
  Account snapshots saved to `~/.gemini/accounts/<email>.json`.
- Model+effort is a single string in `~/.gemini/antigravity-cli/settings.json`.
- Quota errors (`RESOURCE_EXHAUSTED`, `quota reached`, `code 429`, etc.) trigger account rotation. Note: bare `429` is intentionally excluded from the pattern to avoid false positives on Go log timestamps (e.g. `18:40:55.429005`).
- `do-escalate` climbs Flash → Pro → Opus when `AGYKIT_VERIFY` fails.
