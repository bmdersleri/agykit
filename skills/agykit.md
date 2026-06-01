---
name: agykit
description: Use when delegating tasks to agy via agykit — running prompts, escalating code tasks, checking quota, or setting up a project. Invoke before any agykit run/do-escalate call.
---

# agykit Skill

agykit is a quota-aware agy orchestrator. It rotates across multiple Google accounts, escalates through model tiers (Flash → Pro → Opus) when verify fails, and rolls back git changes on failure.

## Command selection

| Task type | Command |
|-----------|---------|
| Explanation, analysis, Q&A | `agykit run "prompt"` |
| Code implementation (needs verify) | `agykit do-escalate "prompt"` |
| Quick state check | `agykit status` |
| Quota details | `agykit quota --status` |
| First-time project setup | `agykit init` |
| Troubleshoot setup | `agykit doctor` |
| List recent jobs | `agykit jobs [N]` |
| Live-stream a running job | `agykit watch <job-id>` |
| View job event history | `agykit job-log <job-id>` |

**Rule:** Use `do-escalate` whenever the task produces code that must be verified.
Use `run` for everything else. Never use plain `agy` directly — agykit handles rotation and fallback.

## Running from Claude Code

Use the `!` prefix to run agykit inline — output lands directly in the conversation:

```
! agykit status
! agykit run "explain the quota detection logic in agykit"
! agykit do-escalate "add retry to agy_quota_status in dashboard/collectors/agy.py"
```

**Workflow:**
1. Claude Code reads files, identifies what needs to change
2. Claude Code writes the exact prompt (file:line scope, constraints, verify hint)
3. User runs `! agykit do-escalate "<prompt>"`
4. Claude Code reviews the result

## Pre-flight check

Before any long task:
```bash
! agykit status       # active account | model | quota summary
! agykit quota --status  # per-model remaining %
```

If quota is low, agykit will rotate to the next available account automatically.

## Writing effective `do-escalate` prompts

Include these 4 elements:
1. **What** — specific, concrete outcome
2. **Where** — exact file paths (and line numbers if relevant)
3. **Constraints** — no new deps, stdlib only, don't touch X
4. **Verify hint** — what passing looks like

**Good:**
```bash
! agykit do-escalate "In dashboard/collectors/agy.py, add retry (3 attempts, 0.5s backoff) \
to agy_quota_status() on FileNotFoundError only. \
Edit only dashboard/collectors/agy.py. \
Tests in tests/test_collectors.py must pass (pytest -q)."
```

**Bad:**
```bash
! agykit do-escalate "fix the quota function"
```

## `do-escalate` escalation behavior

- **Flash** first (cheapest, fastest)
- **Pro** if Flash's output fails `AGYKIT_VERIFY`
- **Opus** if Pro fails
- Each escalation receives the previous model's verify error as context
- On all-fail: agy's changes are rolled back, working tree restored to pre-run state
- Account rotation happens transparently within each tier level

## Token efficiency

- `AGYKIT_FLAGS` must point to source dir, not `$PWD`:
  ```bash
  AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"    # good
  AGYKIT_FLAGS="--add-dir $PWD --dangerously-skip-permissions"        # bad — loads everything
  ```
- `AGYKIT_TERSE="ultra"` for `run` tasks (saves output tokens)
- `AGYKIT_SYSTEM` should point to a concise project context file (`CLAUDE_AGY_SYSTEM.md`)
- Keep `CLAUDE_AGY_SYSTEM.md` under 1KB

## `CLAUDE_AGY_SYSTEM.md` template

Injected as a prefix into every prompt. Edit after `agykit init` creates it.

```markdown
# Project — <name>

<2-3 sentences: what the project does>

## Hard constraints
- Python 3.11+, stdlib only (no new deps)
- Never delete or weaken tests

## Delegation rules (agykit do-escalate)
- Follow the plan exactly. No scope creep.
- Never run git commands. Leave changes unstaged.
- Only edit the files explicitly listed in the prompt.
```

## Job monitoring

Every `run` and `do-escalate` creates a job record. Track running jobs without
opening the dashboard:

```bash
! agykit jobs            # see active and recent jobs
! agykit watch <job-id>  # live 2s-polling status display
! agykit job-log <job-id> # full event history
```

Each job stores a snapshot + event log at `~/.gemini/agykit-jobs/<job_id>.json`.
The dashboard shows an "Aktif Job" card that auto-refreshes with the latest
stage, account, model, and recent events.

## Quota monitoring

```bash
! agykit quota --status      # one-line summary
! agykit quota               # full table with reset times
! agykit dash                # open dashboard (localhost:8787)
```

Alerts fire automatically after each `run`/`do-escalate` success if a model falls below `AGYKIT_QUOTA_ALERT_PCT` (default 15%). Set `AGYKIT_TG_BOT_TOKEN` + `AGYKIT_TG_CHAT_ID` in `.agykit.conf` to receive Telegram notifications.

## Install this skill

```bash
cp "$(dirname $(readlink -f $(which agykit)))/../skills/agykit.md" ~/.claude/skills/agykit.md
```
