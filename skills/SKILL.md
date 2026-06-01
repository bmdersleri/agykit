---
name: agykit
description: Use when user asks to run agy commands, manage Google accounts, switch models, quota rotation, or interact with Antigravity CLI. Keywords: agykit, agy, antigravity, account switch, model switch, do-escalate.
---

# agykit — Antigravity CLI Manager

Portable CLI for Google accounts, model selection, job observability, and dashboard for Antigravity (agy) CLI.

## Installation
```bash
cd /home/haytek/projects/agykit && ./install.sh
```

## Core Commands

| Command | Description |
|---------|-------------|
| `agykit whoami` | Show active Google account |
| `agykit models` | List available model+effort combos |
| `agykit model [name]` | Show or set active model |
| `agykit status` | One-line status: email, model, quota, active job |
| `agykit account-list` | List saved account snapshots |
| `agykit account-save` | Snapshot current keyring login |
| `agykit account-add` | Add new account (guided) |
| `agykit account-remove <email>` | Remove saved account snapshot |
| `agykit switch <email>` | Switch to saved account |
| `agykit run "prompt"` | Quota-aware run with account rotation |
| `agykit do-escalate "prompt"` | Model ladder on verify fail |
| `agykit log [n]` | Show last n ops log entries (default: 20) |
| `agykit doctor [--fix]` | Check/fix dependencies and agy state |
| `agykit init` | Scaffold `.agykit.conf` + `CLAUDE_AGY_SYSTEM.md` |

## Job Observability

Jobs are persisted to SQLite (WAL mode) with real-time events via Unix socket.

| Command | Description |
|---------|-------------|
| `agykit jobs [--limit=N] [--status=] [--command=] [--account=] [--since=] [--until=] [--json]` | List jobs with filters |
| `agykit stats` | Job statistics (total, by status, last 24h) |
| `agykit watch <job-id>` | Live job watch (TUI via Textual if available, terminal fallback) |
| `agykit tail` | Tail events from the most recent active job |
| `agykit cancel <job-id> | --all` | Cancel running jobs |
| `agykit prune [--older-than=N[s\|m\|h\|d]] [--status=] [--dry-run] [--all]` | Housekeeping — remove old jobs |
| `agykit job-log <job-id>` | Full event log for a specific job |

## Dashboard & Quota

| Command | Description |
|---------|-------------|
| `agykit dash [--host=] [--port=]` | Launch web dashboard (localhost, stdlib HTTP/SSE) |
| `agykit quota [--status] [--cache]` | Show/manage quota cache |

Dashboard collectors: agy model quota (tmux), job status, Codex account/usage stats.

## Notifications

Job events can notify via Slack webhook, Telegram bot, or ntfy.sh (set `AGYKIT_JOB_SLACK_WEBHOOK`, `AGYKIT_JOB_TELEGRAM_TOKEN`+`AGYKIT_JOB_TELEGRAM_CHAT_ID`, or `AGYKIT_JOB_NTFY_TOPIC`). Stdlib-only, no extra dependencies.

## run — Quota-aware execution

```bash
agykit run "analyze this code"          # auto-rotates on quota error
AGYKIT_TERSE=full agykit run "..."      # terse output
```

Auto-rotates through saved accounts on quota errors. Stashes uncommitted work first.

## do-escalate — Model ladder

Starts cheap, escalates on verify failure:

1. **Gemini 3.5 Flash** (Medium) — try first
2. **Gemini 3.1 Pro** (High) — on verify fail
3. **Claude Opus 4.6** (Thinking) — last resort

Combines: model escalation + account rotation + stash safety. Original model restored after.

Requires `AGYKIT_VERIFY` in `.agykit.conf`.

## AGYKIT_TERSE — Output compression

| Level | Use case |
|-------|----------|
| `0` / `off` | Default (verbose) |
| `lite` | Human will read output |
| `full` | Mixed human/Claude consumer |
| `ultra` | Claude is consumer — ~60% fewer tokens, zero info loss |

> `ultra` uses `[thing] [action] [reason]` pattern. Code/API/error strings never abbreviated.

## Configuration

Create `.agykit.conf` in project root:
```bash
AGYKIT_VERIFY="just test"        # Verify command for do-escalate
AGYKIT_SYSTEM="CLAUDE.md"        # System context file
AGYKIT_TERSE="ultra"             # Terse output level
AGYKIT_TIMEOUT="15m"             # agy timeout
AGYKIT_FLAGS=""                  # Extra agy flags
```

## Keyring & Account Storage

agy stores OAuth in **system keyring** (`service=gemini, user=antigravity`).

agykit snapshots/swaps keyring items to `~/.gemini/accounts/<email>.json`.

Add new account:
```bash
agykit account-add   # → /logout + login + ctrl+d
```

Active email resolved via Google userinfo.

## Safety Guarantees

- **Tagged stash**: Unique tag (`PID+nanoseconds`) survives agy's own commits
- **Auto-rollback**: On failure, stash restored automatically
- **Pop conflict → loud warning**: "your work is SAFE in `git stash list`"
- **Original state restored**: Model/account after escalation