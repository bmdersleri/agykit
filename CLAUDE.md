# agykit — Claude Context

Portable Antigravity (agy) CLI manager. Multi-account rotation, quota-aware
sorting, model ladder escalation, usage dashboard.

Read `.claude/memory.md` before taking any action.

## Hard Constraints

- **Zero pip dependencies.** Python 3 stdlib only (http.server, json, glob, argparse, webbrowser, datetime, urllib). No FastAPI/uvicorn/flask/pip.
- Bind to `127.0.0.1` only. Read-only access to `~/.claude` and `~/.gemini`.
- Preserve existing style for `agykit` bash changes: `cmd_*` functions + dispatch case.
- Web layer: vanilla JS/HTML/CSS. No frameworks.

## Test

```bash
python3 -m pytest tests -q      # dashboard tests
bash tests/run.sh                # bash safety suites
```

Both must stay green.

## Key Files

- `agykit` — single bash script, main CLI
- `dashboard/server.py` — Python stdlib HTTP/SSE server
- `dashboard/collectors/` — data collectors (agy snapshot, statusline, quota, activity)
- `web/app.js` — dashboard frontend JS
- `web/style.css` — dashboard styles
- `CLAUDE_AGY_SYSTEM.md` — agy delegation rules (for agy, not Claude)

## CLI Reference

### Account Management
```bash
agykit whoami                  # active account email
agykit account-list            # saved snapshots
agykit switch <email>          # switch account (keyring + snapshot)
agykit account-save            # snapshot current session
agykit account-add             # new account: launch agy → login → snapshot
agykit account-remove <email>  # remove snapshot (cannot remove active account)
```

### Task Delegation
```bash
agykit run "prompt"            # simple query/explanation — quota-aware rotation
agykit do-escalate "prompt"    # code task — verify fail → model ladder
```

**When `run`:** Explanation, research, single-step work. No verify needed.  
**When `do-escalate`:** Code change + `AGYKIT_VERIFY` defined (test/lint). Escalates to next model on failure.

Model ladder: Flash → Pro → Opus. Git snapshot at each stage; restores WIP on failure.

### Monitoring
```bash
agykit status                  # one-liner: account | model | quota summary
agykit quota                   # model quota table (5min cache)
agykit quota --refresh         # refresh cache
agykit quota --status          # one-line for scripts
agykit log [N]                 # last N ops log entries (default: 20)
agykit dash [--port N]         # usage dashboard (localhost:7373)
```

### Ops Log (`~/.gemini/agykit-ops.log`)
Every `run` / `do-escalate` call logged as JSONL:
```json
{"ts":"2026-05-31T10:00:00Z","cmd":"run","status":"success","account":"x@y.com","model":"","prompt":"..."}
```
`status` values: `success` | `quota-rotate` | `exhausted` | `verify-failed` | `all-exhausted`  
Rotation: file trimmed to last 400 lines when >512KB.

### Project Setup
```bash
agykit init                    # scaffold .agykit.conf + CLAUDE_AGY_SYSTEM.md
agykit doctor                  # check dependencies and configuration
agykit doctor --fix            # auto-fix resolvable issues
```

### Configuration (`.agykit.conf` or env)
| Variable | Description | Default |
|---|---|---|
| `AGYKIT_VERIFY` | verify command (required for `do-escalate`) | — |
| `AGYKIT_SYSTEM` | system context file path | — |
| `AGYKIT_FLAGS` | extra flags passed to agy | `--dangerously-skip-permissions` |
| `AGYKIT_TIMEOUT` | `--print-timeout` value | `15m` |
| `AGYKIT_TERSE` | output verbosity level | `ultra` |

### `AGYKIT_FLAGS` — `--add-dir` Trap

`--add-dir` flags trigger workspace scan. `_agy_ping` automatically strips them
and runs from `/tmp` — so the project directory is never scanned and the 30s
timeout is never hit. `--dangerously-skip-permissions` is harmless in `/tmp`
(no files to process, no tool loop).

**Account rotation behavior:**
1. Dashboard quota cache can be stale → shows `available` but account is actually exhausted
2. `_agy_ping` runs for every account (30s) — does not trust the cache
3. Ping fail → skip account immediately, try next (no hang)
4. All accounts ping fail → job enters `blocked/failed`, no 15min hang

## Delegation Rules (for agy)

When a task is delegated via `agykit do-escalate` or `run`:
- Follow the given plan/test contract exactly.
- Do not delete, modify, or weaken tests.
- Do not run `git` commands.
- Edit only implementation files.
