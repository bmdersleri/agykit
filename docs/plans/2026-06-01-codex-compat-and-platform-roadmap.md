# agykit: Codex Compatibility & Platform Roadmap

## Goal

Make agykit a first-class citizen across all three major AI coding agents — Claude
Code, OpenCode, and Codex — with feature parity in skill files, system context
injection, CLI commands, and dashboard integrations.

## Current State

| Area | Claude Code | OpenCode | Codex |
|------|-------------|----------|-------|
| Skill file | `skills/agykit.md` | `skills/SKILL.md` | **Missing** |
| System context scaffold | `CLAUDE_AGY_SYSTEM.md` | manual | **Missing** |
| Dashboard collector | `claude.py` | — | `codex.py` |
| CLI command | `agykit status` reads Claude data | — | **Missing** |

## Phase 1 — Codex Skill & System Context

**Files to create/modify:**
- `skills/codex.md` (new)
- `agykit` — `cmd_init()` to detect agent and create the right system context file

**Details:**

1. Create `skills/codex.md`:
   - Follow the same structure as `skills/agykit.md` but adapted for Codex
   - Codex uses `/` slash commands and config-based agent delegation (no `!` prefix)
   - Reference `~/.codex/skills/` install path
   - Show how to configure Codex agents to delegate through agykit
   - Include example Codex agent config (TOML) that maps commands to `agykit run` / `agykit do-escalate`

2. Update `cmd_init()`:
   - Detect running agent (Claude Code vs Codex vs OpenCode)
   - For Codex: create `CODEX_AGY_SYSTEM.md` and update `.agykit.conf`
   - Auto-detect: check `CODEX_API_KEY`, `CLAUDE_CODE`, or `OPENCODE` env vars

3. Update `install.sh`:
   - Install `skills/codex.md` to `~/.codex/skills/agykit.md` when Codex is present
   - Install `skills/SKILL.md` to `~/.agents/skills/agykit/SKILL.md` when OpenCode is present

**Verification:**
```bash
ls ~/.codex/skills/agykit.md
agykit init  # inside a test project — should create correct system file
```

## Phase 2 — `agykit codex` CLI Command

**Files to create/modify:**
- `agykit` — new `cmd_codex()` function + dispatch entry
- `dashboard/collectors/codex.py` — already exists, may need minor extension

**Details:**

1. Add `cmd_codex()`:
   - `agykit codex` — show full Codex usage report (account, plan, model, threads, tokens)
   - `agykit codex --status` — one-line summary for statusline
   - `agykit codex --json` — machine-readable output
   - Reuse `codex_status()` and `codex_usage()` from `dashboard/collectors/codex.py`

2. Add dispatch case:
   - `codex)  cmd_codex "${@:2}" ;;`

3. Update `agykit status`:
   - Append Codex info when available (like it appends active job info)

**Verification:**
```bash
agykit codex
agykit codex --json | jq '.account.plan_type'
```

## Phase 3 — Dashboard Codex Cards

**Files to modify:**
- `web/index.html` — add Codex account card
- `web/app.js` — fetch `/api/codex-status` and render card
- `dashboard/server.py` — add `/api/codex-status` SSE endpoint

**Details:**

1. Add `/api/codex-status` SSE endpoint:
   - Returns `codex_status()` data (plan type, email, model, thread count, token usage)
   - Subscribe to file-change mtime for live refresh

2. Dashboard card:
   - Show Codex account info (email, plan type, subscription active until)
   - Current model, active thread count, total tokens used
   - Warning banner if Codex data unavailable

3. Existing prompt/thread cards are already rendered — align styling

**Verification:**
```bash
curl http://127.0.0.1:7373/api/codex-status
```

## Phase 4 — Auto-Detect Agent for System Context

**Files to modify:**
- `agykit` — `_system_prefix()` to detect agent at runtime
- `agykit` — `cmd_init()` already updated in Phase 1

**Details:**

1. Add `_detect_agent()`:
   - Returns `"claude"`, `"codex"`, `"opencode"`, or `"unknown"`
   - Check: `CLAUDE_CODE` env, `CODEX_API_KEY` env, `OPENCODE` env
   - Fallback: check `~/.claude/`, `~/.codex/`, `~/.config/opencode/` directory existence

2. Update `_system_prefix()`:
   - When `AGYKIT_SYSTEM` not set, pick default based on detected agent:
     - Claude → `CLAUDE_AGY_SYSTEM.md`
     - Codex → `CODEX_AGY_SYSTEM.md`
     - OpenCode → `OPENCODE_AGY_SYSTEM.md`
   - Still respect explicit `AGYKIT_SYSTEM` env var

3. Update `cmd_doctor()`:
   - Check the correct system file for the detected agent

**Verification:**
```bash
CODEX_API_KEY=test agykit run "hello"  # should use CODEX_AGY_SYSTEM.md
```

## Phase 5 — RTK CLI Wrapper

**Files to modify:**
- `agykit` — new `cmd_rtk()` function + dispatch entry
- `dashboard/collectors/rtk.py` — already exists

**Details:**

1. Add `cmd_rtk()`:
   - `agykit rtk` — show RTK token savings summary
   - `agykit rtk --json` — machine-readable
   - Wraps `rtk_stats()` from `dashboard/collectors/rtk.py`

2. Update `agykit status`:
   - Append RTK efficiency when available

**Verification:**
```bash
agykit rtk
agykit rtk --json | jq '.efficiency_pct'
```

## Phase 6 — TUI Dependency Resolution

**Files to modify:**
- `dashboard/tui.py` — make Textual optional with stdlib fallback

**Details:**

1. Current behavior:
   - `cmd_job_watch()` tries TUI first (Textual required), falls back to polling
   - TUI import failure → raises ImportError, caught by the bash `2>/dev/null` guard

2. Improve by making `watch_job_tui()` gracefully degrade:
   - Wrap `from textual import ...` in try/except ImportError
   - Return `False` immediately when Textual not installed
   - Move the fallback logic inside Python instead of relying on bash exit codes

**Verification:**
```bash
pip uninstall textual -y
agykit watch <job-id>  # should still work via polling fallback
```

## Phase 7 — Dashboard SSE Auto-Refresh

**Files to modify:**
- `dashboard/server.py` — SSE endpoints for live data
- `web/app.js` — EventSource listeners

**Details:**

1. Current: dashboard polls on page load, manual refresh
2. Add SSE streams for:
   - `/events/jobs` — live job status changes
   - `/events/quota` — quota cache changes
3. Frontend subscribes via `EventSource` and updates cards in real-time

**Verification:**
```bash
# Terminal 1: dashboard running
# Terminal 2: agykit run "..."  → dashboard card updates without refresh
```

## Phase 8 — End-to-End Tests

**Files to create/modify:**
- `tests/test_codex_compat.sh` (new)
- `tests/test_cli_commands.sh` (new)
- `tests/test_dashboard_sse.py` (new, optional)

**Details:**

1. Codex compat tests:
   - Verify `agykit codex` runs without error (graceful if no Codex data)
   - Verify `CODEX_AGY_SYSTEM.md` is used when agent is Codex
   - Verify skill file install paths

2. CLI command tests:
   - Smoke test every registered command (help text, exit codes)
   - Verify JSON output is valid JSON

3. Dashboard SSE tests:
   - Connect to SSE endpoint, verify initial data event
   - Trigger a job event, verify it appears in SSE stream

**Verification:**
```bash
bash tests/test_codex_compat.sh
bash tests/test_cli_commands.sh
```

## Summary

| Phase | Scope | Files | Effort |
|-------|-------|-------|--------|
| 1 | Codex skill + system context | 3 new, 2 modify | Small |
| 2 | `agykit codex` CLI command | 1 modify | Small |
| 3 | Dashboard Codex cards | 3 modify | Medium |
| 4 | Auto-detect agent for system file | 1 modify | Small |
| 5 | RTK CLI wrapper | 1 modify | Small |
| 6 | TUI dependency resolution | 1 modify | Small |
| 7 | Dashboard SSE auto-refresh | 2 modify | Medium |
| 8 | End-to-end tests | 2-3 new | Medium |
