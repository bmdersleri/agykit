# agykit Project Context

agykit v1.4.0 — Portable Antigravity (agy) CLI manager. Shell entrypoint (`agykit`) delegates `run` and `do-escalate` to a Python subprocess orchestrator (`dashboard/orchestrator.py`). Includes a usage dashboard (`dashboard/`) and vanilla frontend (`web/`).

## Architecture

```
agykit (bash)
  cmd_run          → dashboard.orchestrator run      (Python)
  cmd_do_escalate  → dashboard.orchestrator escalate (Python)
  all other cmds   → stay in bash

dashboard/orchestrator.py
  OrchestratorBase     — subprocess streaming, silence detection (120s), ping (15s)
  RunOrchestrator      — account rotation, quota detection, cache invalidation
  EscalateOrchestrator — model ladder, 3-attempt retry with backoff, verify, git rollback
```

## Hard constraints (NON-NEGOTIABLE)
- **Zero pip dependencies.** Python 3 standard library ONLY (http.server, json,
  glob, argparse, webbrowser, datetime, urllib, subprocess). NO fastapi/uvicorn/flask/pip.
- Bind `127.0.0.1` only. Read-only on `~/.claude` and `~/.gemini`.
- Match existing bash style for any `agykit` edits (cmd_* fns + dispatch case).

## Test / verify
- `python3 -m pytest tests -q` (dashboard + orchestrator tests) must pass.
- `bash tests/run.sh` (bash safety suites) must stay green.

## Key env vars (for tasks that touch orchestrator)
- `AGYKIT_SILENCE_TIMEOUT` — seconds without output before orchestrator kills agy (default: 120)
- `AGYKIT_JOB_TIMEOUT` — hard job ceiling in seconds (default: 1800)
- `AGYKIT_VERIFY` — verify command for do-escalate
- `AGYKIT_FLAGS` — extra agy flags (default: `--dangerously-skip-permissions`)

## OpenCode tooling notes
- Use the edit/write tools for changes; keep edits scoped to the named files.
- If the worktree is dirty, assume existing changes belong to the user — do not
  revert or clean them unless explicitly asked.
- `agykit do-escalate` snapshots/restores the git worktree internally via the Python
  orchestrator; never duplicate that with destructive git commands.

## Delegation rules (for agy)
When a task is delegated to you via agykit (do-escalate/run):
- Follow the given plan / test contract EXACTLY. No scope creep.
- Do NOT delete/modify/weaken tests. Make FAILing tests pass (write implementation).
- No tautological/empty tests. You don't need to add tests — they're ready.
- Do NOT run git commands (commit/reset/rebase/push/stash). Leave changes in the
  working tree.
- Create/edit only implementation files:
  `dashboard/`, `dashboard/orchestrator.py`, `dashboard/collectors/`, `dashboard/server.py`,
  `web/`, `agykit` (bash wiring), `README.md`.
- Reply tersely.
