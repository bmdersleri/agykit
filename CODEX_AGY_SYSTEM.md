# agykit Project Context

Portable Antigravity (agy) CLI manager. Core is a single bash script `agykit`.
Includes a usage **dashboard** under `dashboard/` (Python 3 stdlib only) and
vanilla frontend assets under `web/`.

## Hard constraints (NON-NEGOTIABLE)
- **Zero pip dependencies.** Python 3 standard library ONLY (http.server, json,
  glob, argparse, webbrowser, datetime, urllib). NO fastapi/uvicorn/flask/pip.
- Bind `127.0.0.1` only. Read-only on `~/.claude` and `~/.gemini`.
- Match existing bash style for any `agykit` edits (cmd_* fns + dispatch case).

## Test / verify
- `python3 -m pytest tests -q` (dashboard + collector tests) must pass.
- `bash tests/run.sh` (bash safety suites) must stay green.

## Codex tooling notes
- Prefer `apply_patch` for edits; `rg` for search, `fd`/`fdfind` for files.
- If the worktree is dirty, assume existing changes belong to the user — do not
  revert or clean them unless explicitly asked.
- `agykit do-escalate` snapshots/restores the git worktree internally; never
  duplicate that with destructive git commands.

## Delegation rules (for agy)
When a task is delegated to you via agykit (do-escalate/run):
- Follow the given plan / test contract EXACTLY. No scope creep.
- Do NOT delete/modify/weaken tests. Make FAILing tests pass (write implementation).
- No tautological/empty tests. You don't need to add tests — they're ready.
- Do NOT run git commands (commit/reset/rebase/push/stash). Leave changes in the
  working tree.
- Create/edit only implementation files:
  `dashboard/collectors/`, `dashboard/server.py`, `dashboard/quota.py`,
  `dashboard/alerts.py`, `web/`, `agykit` (bash wiring), `README.md`.
- Reply tersely.
