# agykit — Claude Context

agykit v1.4.0 — Portable Antigravity (agy) CLI manager. Multi-account rotation, quota-aware sorting, model ladder escalation, Python subprocess orchestrator, usage dashboard.

Read `.claude/memory.md` before taking any action.

## Hard Constraints

- **Zero pip dependencies.** Python 3 stdlib only (http.server, json, glob, argparse, webbrowser, datetime, urllib, subprocess). No FastAPI/uvicorn/flask/pip.
- Bind to `127.0.0.1` only. Read-only access to `~/.claude` and `~/.gemini`.
- Preserve existing style for `agykit` bash changes: `cmd_*` functions + dispatch case.
- Web layer: vanilla JS/HTML/CSS. No frameworks.

## Test

```bash
python3 -m pytest tests -q      # dashboard + orchestrator tests
bash tests/run.sh                # bash safety suites
```

Both must stay green.

## Key Files

- `agykit` — bash entrypoint; `cmd_run` and `cmd_do_escalate` delegate to Python orchestrator
- `dashboard/orchestrator.py` — Python subprocess orchestrator (RunOrchestrator, EscalateOrchestrator)
- `dashboard/server.py` — Python stdlib HTTP/SSE server
- `dashboard/collectors/` — data collectors (agy snapshot, statusline, quota, activity)
- `dashboard/collectors/agy.py` — quota cache with dynamic TTL (`_effective_quota_ttl`)
- `dashboard/collectors/jobs.py` — SQLite job store, PID-aware recovery
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
agykit wait [job-id]           # block until a job ends (exit 0=ok 1=fail 2=timeout)
agykit tasks list [spec.md]    # list tasks in a spec file
agykit tasks run [--task <id>] [spec.md]  # run one or all tasks via do-escalate
```

**When `run`:** Explanation, research, single-step work. No verify needed.  
**When `do-escalate`:** Code change + `AGYKIT_VERIFY` defined (test/lint). Escalates to next model on failure.

Model ladder: Flash → Pro → Opus. Git snapshot at each stage; restores WIP on failure.

**Account order:** `run`/`do-escalate` try the currently switched-in account
(`agykit switch <email>`) FIRST, then the rest by quota — so a manual switch
decides where the job runs. If the active account is exhausted it falls through
to pure quota order.

**Completion:** `run`/`do-escalate` are synchronous and print `==> job: <id>` at
start. They run under the launching shell's PID, so a job is "done" only when
that process exits — recovery never marks a live job stale during agy's long
silent phase. To gate a script on a backgrounded job, use `agykit wait` (its
exit code is the job result), not `watch` (interactive TUI).

### Task Spec Format (`.agykit-tasks.md`)

Task specs are Markdown files parsed by `agykit tasks`. The parser uses a strict
regex — wrong header format means the task is silently skipped.

**File location:** default is `.agykit-tasks.md` in CWD, or set `AGYKIT_TASKS_FILE`
in `.agykit.conf`, or pass the path explicitly: `agykit tasks list path/to/file.md`.

#### Header formats (both accepted)

**Canonical (preferred):**
```markdown
## task-<id>: Title of the task
```
- `task-` prefix required, followed by lowercase letters, digits, or hyphens
- Colon `:` or space after the id — both work
- Examples: `## task-1: Create base.html`, `## task-auth: Add JWT middleware`

**Legacy numeric (also accepted):**
```markdown
## Task 3 — Title of the task
## Task 3: Title of the task
## Task 3 - Title of the task
```
- `Task` (capital T) + space + digit(s) + separator (`—`, `:`, `-`, `–`)
- Parser auto-generates id as `task-3`

**NOT accepted (silent skip):**
```markdown
### Task 1 — Title    ← wrong level (### not ##)
## task1: Title       ← missing hyphen in id (task1 not task-1... actually this fails group 1 regex)
## TASK 1 — Title     ← wrong case
## 1. Title           ← no "Task" prefix
```

#### Optional metadata lines (immediately after the header, before the prompt)

```
depends_on: [task-1, task-2]
verify_hint: check that src/foo.py exists and imports Bar
```

- `depends_on` — task IDs that must succeed first (used by `tasks run` ordering)
- `verify_hint` — extra hint passed to the verifier (not yet enforced, reserved)
- Both are stripped from the prompt before sending to agy

#### Prompt body

Everything after the header line (and optional metadata) becomes the prompt
passed verbatim to `agykit do-escalate`. Rules:

- Write the full, self-contained prompt. Do not reference other tasks by "see above" —
  agy has no context from prior tasks.
- Use fenced code blocks for file content or CLI commands within the prompt.
- Include: file path(s) to create/edit, exact requirements, what NOT to do.
- The prompt is trimmed (leading/trailing whitespace stripped).

#### Full example

```markdown
# My Feature — agykit Tasks

## task-base: Create base template
depends_on: []
verify_hint: src/templates/base.html must exist

Create src/templates/base.html — a Jinja2 base template.

Requirements:
- DOCTYPE html, lang="en", charset UTF-8
- Block named "content" for page body
- Block named "extra_scripts" at body end
- Do NOT create any Python files

## task-styles: Add shared CSS
depends_on: [task-base]

Create src/static/style.css with shared card and badge styles:

.card { background: #1a1b23; border-radius: 12px; padding: 1.25rem; }
.badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 6px; }

Do NOT modify any existing file.
```

#### Running tasks

```bash
agykit tasks list                        # list all tasks + ids from default file
agykit tasks list path/to/tasks.md       # list from explicit file
agykit tasks run                         # run all tasks in order
agykit tasks run --task task-base        # run one specific task
agykit tasks run path/to/tasks.md        # run all from explicit file
agykit tasks run --task task-base path/to/tasks.md
```

`tasks run` calls `do-escalate --force` per task — verify runs after each one.
A task that fails verify causes the run to stop (does not cascade to next task).

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
agykit update                  # git fetch + ff-only pull, prints old → new version
agykit doctor                  # check dependencies and configuration
agykit doctor --fix            # auto-fix resolvable issues
```

### Configuration (`.agykit.conf` or env)
| Variable | Description | Default |
|---|---|---|
| `AGYKIT_VERIFY` | verify command (required for `do-escalate`) | — |
| `AGYKIT_SYSTEM` | system context file path | — |
| `AGYKIT_FLAGS` | extra flags passed to agy | `--dangerously-skip-permissions` |
| `AGYKIT_TIMEOUT` | agy `--print-timeout` value | `15m` |
| `AGYKIT_SILENCE_TIMEOUT` | seconds without output before orchestrator kills agy | `120` |
| `AGYKIT_JOB_TIMEOUT` | hard job ceiling (s); reap + SIGTERM past this. Keep ≥ `AGYKIT_TIMEOUT` | `1800` |
| `AGYKIT_TERSE` | output verbosity level | `ultra` |
| `AGYKIT_AGENT` | force orchestrator agent: `claude`/`codex`/`opencode` (else auto-detect) | auto |
| `AGYKIT_ARCHITECT_ESCALATE` | architect fallback when ladder fails: `auto`/`claude`/`codex`/`opencode`/path | — |
| `AGYKIT_ARCHITECT_MODEL` | model for opencode architect (`-m provider/model`) | — |

### Agent compatibility (Claude Code / Codex / OpenCode)

agykit is orchestrator-agnostic — same backend (`agy`), runs from any agent.
`_detect_agent` resolves which agent is driving, in priority order:

1. `AGYKIT_AGENT` override
2. **Runtime env** — `CLAUDE_CODE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` → claude;
   `CODEX_*` → codex; `OPENCODE*` → opencode. (Env beats on-disk config so a box
   with all three CLIs installed still detects the live one.)
3. **Installed-file fallback** (plain shell) — `~/.codex/auth.json|config.toml`,
   `~/.claude/.credentials.json`, `~/.config/opencode/opencode.json`
4. `unknown`

Detection drives the injected system file (`{CLAUDE,CODEX,OPENCODE}_AGY_SYSTEM.md`)
and architect-escalate routing. Verified invocations: `claude -p`, `codex exec`,
`opencode run [-m provider/model]`. Check with `agykit doctor` → Agent Integration.

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
