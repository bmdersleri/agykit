# agykit Skill (OpenCode)

agykit is a quota-aware agy orchestrator. It rotates across multiple Google
accounts, escalates through model tiers (Flash -> Pro -> Opus) when verify
fails, and rolls back git changes on failure.

## When to use agykit

| Task type | Command |
|-----------|---------|
| Explanation, analysis, Q&A | `agykit run "prompt"` |
| Code implementation (needs verify) | `agykit do-escalate "prompt"` |
| Quick state check | `agykit status` |
| Quota details | `agykit quota --status` |
| RTK token savings | `agykit rtk` |
| First-time project setup | `agykit init` |
| Troubleshoot setup | `agykit doctor` |
| List recent jobs | `agykit jobs [N]` |
| Filter jobs | `agykit jobs --status failed --since 24h` |
| Job statistics | `agykit stats` |
| Live-stream a running job | `agykit watch <job-id>` |
| Block until a job ends | `agykit wait [job-id]` |
| View job event history | `agykit job-log <job-id>` |
| Cancel a job | `agykit cancel <job-id>` |
| Prune old jobs | `agykit prune --older-than 7d` |

**Rule:** Use `do-escalate` whenever the task produces code that must be
verified. Use `run` for everything else. Never use plain `agy` directly --
agykit handles rotation and fallback.

## Running from OpenCode

OpenCode runs shell commands directly -- no special prefix needed:

```bash
agykit status
agykit run "explain the quota detection logic in agykit"
agykit do-escalate "add retry to agy_quota_status in dashboard/collectors/agy.py"
```

agykit detects it is running under OpenCode automatically (via OpenCode env
signals, then `~/.config/opencode/opencode.json`). Force it with
`AGYKIT_AGENT=opencode` if needed. The injected system context file is
`OPENCODE_AGY_SYSTEM.md` when present.

**Workflow:**
1. OpenCode reads files, identifies what needs to change
2. OpenCode writes the exact prompt (file:line scope, constraints, verify hint)
3. OpenCode runs `agykit do-escalate "<prompt>"`
4. OpenCode reviews the result (or `agykit wait` to block on a backgrounded job)

## Pre-flight check

Before any long task:
```bash
agykit status          # active account | model | quota summary
agykit quota --status  # per-model remaining %
```

If quota is low, agykit will rotate to the next available account automatically.

## Writing effective `do-escalate` prompts

Include these 4 elements:
1. **What** -- specific, concrete outcome
2. **Where** -- exact file paths (and line numbers if relevant)
3. **Constraints** -- no new deps, stdlib only, don't touch X
4. **Verify hint** -- what passing looks like

**Good:**
```bash
agykit do-escalate "In dashboard/collectors/agy.py, add retry (3 attempts, 0.5s backoff) \
to agy_quota_status() on FileNotFoundError only. \
Edit only dashboard/collectors/agy.py. \
Tests in tests/test_collectors.py must pass (pytest -q)."
```

**Bad:**
```bash
agykit do-escalate "fix the quota function"
```

## `do-escalate` escalation behavior

- **Flash** first (cheapest, fastest)
- **Pro** if Flash's output fails `AGYKIT_VERIFY`
- **Opus** if Pro fails
- Each escalation receives the previous model's verify error as context
- On all-fail: agy's changes are rolled back, working tree restored to
  pre-run state
- Account rotation happens transparently within each tier level
- Optional: set `AGYKIT_ARCHITECT_ESCALATE=auto` (or `opencode`) to get an
  architect review from your agent CLI after all models fail

## Architect escalation from OpenCode

When the model ladder is exhausted, agykit can call an agent CLI as the
architect for a root-cause + fix plan:

```bash
AGYKIT_ARCHITECT_ESCALATE=opencode \
AGYKIT_ARCHITECT_MODEL=anthropic/claude-sonnet-4-6 \
  agykit do-escalate "<task>"
```

`auto` routes to whichever agent agykit detects it is running under.

## Job monitoring

Every `run` and `do-escalate` creates a job record:

```bash
agykit jobs             # see active and recent jobs
agykit watch <job-id>   # live 2s-polling status display
agykit wait <job-id>    # block until terminal (exit 0=ok 1=fail 2=timeout)
agykit job-log <job-id> # full event history
```

## Quota monitoring

```bash
agykit quota --status      # one-line summary
agykit quota               # full table with reset times
agykit dash                # open dashboard (localhost:8787)
```

## Install this skill

```bash
# OpenCode skills live under ~/.agents/skills/ (shared agents skill dir)
cp /path/to/agykit/skills/opencode.md ~/.agents/skills/agykit/SKILL.md
```
