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
```

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
- Quota errors (`429`, `RESOURCE_EXHAUSTED`, etc.) trigger account rotation.
- `do-escalate` climbs Flash → Pro → Opus when `AGYKIT_VERIFY` fails.
