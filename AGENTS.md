# Agent Instructions for agykit

This repository builds `agykit`, a portable Antigravity (`agy`) CLI manager.
It is intended to work from Claude Code, OpenCode, Codex, or a plain shell.

Before installing or recommending new CLI tools, read:

```text
/home/haytek/ai-tooling/AI_TOOLING.md
```

## Project Shape

- `agykit` is the main Bash CLI. Keep the existing style: `cmd_*` functions plus
  the dispatch `case` near the end of the file.
- `dashboard/server.py` is a Python stdlib HTTP/SSE server bound to localhost.
- `dashboard/collectors/` contains the dashboard data collectors.
- `dashboard/quota.py` is the standalone quota cache/CLI wrapper.
- `dashboard/alerts.py` handles quota alert checks and notification side effects.
- `web/` is the vanilla HTML/CSS/JS dashboard frontend.
- `tests/` contains Python and shell safety tests.
- `CLAUDE_AGY_SYSTEM.md`, `CODEX_AGY_SYSTEM.md`, `OPENCODE_AGY_SYSTEM.md` are
  system context files injected into delegated `agy` prompts — one per agent.
  `_agent_system_file()` selects the right one based on `_detect_agent()`.
- `.agykit.conf` configures this repo's own dogfood setup.

## Hard Constraints

- No new runtime dependencies. Python code must use the standard library only.
- Do not add FastAPI, Flask, uvicorn, requests, frontend frameworks, bundlers, or
  package-manager metadata unless the user explicitly asks.
- Bind local services to `127.0.0.1` only.
- Treat `~/.claude` and `~/.gemini` data as user-owned; read only unless an
  existing agykit command is explicitly designed to write there.
- Do not delete, weaken, or bypass tests.
- Keep edits scoped. Avoid unrelated refactors and formatting churn.

## Commands

Run the full verification before claiming code changes are complete:

```bash
python3 -m pytest tests -q
bash tests/run.sh
```

Useful focused checks:

```bash
python3 -m pytest tests/test_collectors.py -q
python3 -m pytest tests/test_server.py -q
python3 -m pytest tests/test_alerts.py -q
bash tests/test_do_escalate.sh
bash tests/test_git_safety.sh
```

Dashboard smoke run:

```bash
python3 dashboard/server.py --host 127.0.0.1 --port 7373
```

Project-native agykit configuration:

```bash
AGYKIT_VERIFY="python3 -m pytest tests -q && bash tests/run.sh"
AGYKIT_SYSTEM="CLAUDE_AGY_SYSTEM.md"
AGYKIT_FLAGS="--add-dir $PWD/dashboard --dangerously-skip-permissions"
```

## Development Notes

- Prefer `rg` for search and `fd`/`fdfind` for file discovery.
- Prefer `jq`/`yq` for structured data.
- Use `apply_patch` for manual edits.
- If the worktree is dirty, assume existing changes belong to the user. Do not
  revert or clean them unless explicitly asked.
- Be careful with `agykit do-escalate`: it snapshots/restores the git worktree
  internally. Do not duplicate that behavior with destructive git commands.
- The current collector API is the `dashboard.collectors` package, not the old
  single-file `dashboard/collectors.py` module.

## Delegating Through agykit

Use `agykit run` for explanation and analysis prompts.
Use `agykit do-escalate` for implementation tasks that must pass verify.

Good delegated prompts include:

- exact files and functions to edit
- constraints such as "stdlib only" and "do not touch tests"
- expected verify command
- narrow scope with no unrelated cleanup

Example:

```bash
agykit do-escalate "In dashboard/collectors/agy.py, fix quota parsing for empty tmux output. Edit only dashboard/collectors/agy.py. Do not add dependencies. Verify with python3 -m pytest tests/test_collectors.py -q."
```
