# agykit Skill (Codex)

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
| Codex account info | `agykit codex` |
| RTK token savings | `agykit rtk` |
| First-time project setup | `agykit init` |
| Troubleshoot setup | `agykit doctor` |
| List recent jobs | `agykit jobs [N]` |
| Filter jobs | `agykit jobs --status failed --since 24h` |
| Job statistics | `agykit stats` |
| Live-stream a running job | `agykit watch <job-id>` |
| View job event history | `agykit job-log <job-id>` |
| Cancel a job | `agykit cancel <job-id>` |
| Prune old jobs | `agykit prune --older-than 7d` |

**Rule:** Use `do-escalate` whenever the task produces code that must be
verified. Use `run` for everything else. Never use plain `agy` directly --
agykit handles rotation and fallback.

## Running from Codex

Codex runs shell commands directly -- no special prefix needed:

```bash
agykit status
agykit run "explain the quota detection logic in agykit"
agykit do-escalate "add retry to agy_quota_status in dashboard/collectors/agy.py"
```

**Workflow:**
1. Codex reads files, identifies what needs to change
2. Codex writes the exact prompt (file:line scope, constraints, verify hint)
3. Codex runs `agykit do-escalate "<prompt>"`
4. Codex reviews the result

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

## Token efficiency

- `AGYKIT_FLAGS` must point to source dir, not `$PWD`:
  ```bash
  AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"    # good
  AGYKIT_FLAGS="--add-dir $PWD --dangerously-skip-permissions"        # bad
  ```
- `AGYKIT_TERSE="ultra"` for `run` tasks (saves output tokens)
- Set `AGYKIT_SYSTEM` to a concise project context file
- Keep the system context file under 1KB

## Job monitoring

Every `run` and `do-escalate` creates a job record:

```bash
agykit jobs             # see active and recent jobs
agykit watch <job-id>   # live 2s-polling status display
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
cp /path/to/agykit/skills/codex.md ~/.codex/skills/agykit.md
```
