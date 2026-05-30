---
name: agykit
description: Use when delegating tasks to agy via agykit — running prompts, escalating code tasks, checking quota, or setting up a project. Invoke before any agykit run/do-escalate call.
---

# agykit Skill

## Command selection

| Task type | Command |
|-----------|---------|
| Explanation, analysis, Q&A | `agykit run "prompt"` |
| Code implementation (needs verify) | `agykit do-escalate "prompt"` |
| Quick state check | `agykit status` |
| Quota details | `agykit quota` |
| First-time project setup | `agykit init` |
| Troubleshoot setup | `agykit doctor` |

**Rule:** Use `do-escalate` whenever the task produces code that must be verified.
Use `run` for everything else. Never use plain `agy` directly — agykit handles rotation and fallback.

## Pre-flight check

Before any long task:
```bash
agykit status    # active account | model | quota summary
agykit doctor    # if something seems off
```

If quota is low, agykit will rotate to the next available account automatically.

## Writing effective do-escalate prompts

Include:
1. **What to implement** — specific, concrete outcome
2. **Which files to touch** — explicit list
3. **Hard constraints** — no new deps, stdlib only, etc.
4. **Verification hint** — what passing tests look like

Example:
```bash
agykit do-escalate "Add retry logic to dashboard/collectors.py::agy_quota_status().
Retry up to 3 times on FileNotFoundError with 0.5s backoff.
Only edit dashboard/collectors.py. Tests in tests/test_collectors.py must pass."
```

Bad (too vague):
```bash
agykit do-escalate "fix the quota function"
```

## do-escalate escalation behavior

Starts at Flash (cheapest), escalates to Pro → Opus only when `AGYKIT_VERIFY` fails.
Each escalation passes the previous model's verify error as context — no need to repeat what failed.

If all 3 models fail: changes are rolled back, working tree is restored to pre-run state.

## Token efficiency

- `AGYKIT_FLAGS` must point to source dir, not `$PWD`:
  ```bash
  AGYKIT_FLAGS="--add-dir $PWD/src --dangerously-skip-permissions"  # good
  AGYKIT_FLAGS="--add-dir $PWD --dangerously-skip-permissions"       # bad — loads everything
  ```
- `AGYKIT_TERSE="ultra"` for `run` tasks (saves output tokens, quota lasts longer)
- `AGYKIT_SYSTEM` should point to a concise project context file (`CLAUDE_AGY_SYSTEM.md`)

## CLAUDE_AGY_SYSTEM.md template

This file is injected as a prefix into every agykit run/do-escalate prompt.
Keep it under 1KB. Include:

```markdown
# Project — Context

<2-3 sentences: what the project does>

## Hard constraints
- <language version, zero-dep rules, etc.>

## Delegation rules (when invoked via agykit do-escalate)
- Follow the given plan exactly. No scope creep.
- Never delete or weaken tests.
- Never run git commands. Leave changes in working tree.
- Only edit: <explicit file list>
```

## Install this skill

Copy to your Claude Code skills directory:
```bash
cp "$(dirname $(which agykit))/../skills/agykit.md" ~/.claude/skills/agykit.md
```
