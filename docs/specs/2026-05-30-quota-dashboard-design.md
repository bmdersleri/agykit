# Quota Dashboard — Design

**Date:** 2026-05-30
**Project:** agykit
**Status:** Approved (pending spec review)

## Problem

No graphical way to track Claude Code and agy (Antigravity) usage over time. The
user wants a live dashboard that charts how much of each tool's quota is being
burned, day over day.

## Data reality (what actually exists)

**Claude Code — strong, ready:**
- `~/.claude/stats-cache.json` (schema v3) holds pre-aggregated daily series:
  - `dailyActivity[]`: `date`, `messageCount`, `sessionCount`, `toolCallCount`
  - `dailyModelTokens[]`: `date`, `tokensByModel{ <model>: <int> }`
- True 5h / weekly subscription quota percentage is **not** in a stable file
  (`/usage` shows it but is not file-backed). v1 charts token *usage*, not a
  remaining-quota gauge.

**agy (Antigravity) — partial:**
- `~/.gemini/antigravity-cli/brain/<uuid>/.system_generated/logs/transcript_full.jsonl`
  — one dir per session (~102 sessions, ~57 MB). Each record has `created_at`,
  `type`, `source`, `status`, `step_index`, `tool_calls`, `model`/`content`.
  **No token counts, no quota numbers.**
- Derivable history: sessions/day, tool-calls/day, model mix, activity timeline
  (from `created_at` timestamps + record types).
- The agy statusline JSON (`context_window.used_percentage`, `plan_tier`,
  `email`, per-session token totals) is **ephemeral** — fed live by agy on
  stdin while running, never persisted. Capturing it requires instrumenting
  agykit per run (deferred to phase 2).
- No persisted quota counter anywhere; a `429 / RESOURCE_EXHAUSTED` is the only
  exhaustion signal, detected reactively by `agykit run`.

**Honest v1 scope:** chart usage/activity *history* from files that already
exist. Claude = tokens-by-model + activity. agy = session / tool-call / model
activity. A true live "remaining quota" gauge is phase 2.

## Constraints

- **agykit is a bash project, dependency-light, orchestrator-agnostic.** The
  dashboard MUST preserve that: **zero pip dependencies — Python 3 standard
  library only.** No FastAPI / uvicorn (those belong to the komite repo, not
  here). Python 3.13 is available.
- Localhost only (`127.0.0.1`). Reads local user files; binds no public port.
- Read-only with respect to Claude/agy data — never writes into `~/.claude` or
  `~/.gemini`.

## Architecture

A small self-contained dashboard launched via a new `agykit dash` subcommand.

```
agykit (bash)  --dash-->  python3 dashboard/server.py
                                   |
                  +----------------+----------------+
                  | collectors.py  |  index.html     |
                  | (claude + agy) |  (+ Chart.js CDN)|
                  +----------------+----------------+
                          reads
              ~/.claude/stats-cache.json
              ~/.gemini/antigravity-cli/brain/*/.../transcript_full.jsonl
```

### Components

1. **`dashboard/collectors.py`** — pure functions, stdlib only.
   - `claude_series(range_days) -> dict` — parse `stats-cache.json` into daily
     series: total tokens, tokens-by-model, messages, sessions, tool calls.
   - `agy_series(range_days) -> dict` — scan brain `transcript_full.jsonl`
     files; bucket by `created_at` date into: sessions/day, tool-calls/day,
     model mix. Tolerant of malformed lines and missing fields.
   - Each returns a JSON-serializable dict of `{ labels: [dates], datasets: ... }`.
   - A `STATS_CACHE` / `BRAIN_DIR` path constant, overridable via env for tests.

2. **`dashboard/server.py`** — `http.server.ThreadingHTTPServer` + a
   `BaseHTTPRequestHandler`. Routes:
   - `GET /` -> serve `index.html`.
   - `GET /api/data?source=claude|agy&range=7d|30d|all` -> JSON from collectors.
   - `GET /events` -> SSE (`Content-Type: text/event-stream`). Server polls the
     mtime of `stats-cache.json` and the newest brain transcript every ~3 s;
     when either changes it pushes a `data: refresh\n\n` event. Client refetches
     `/api/data` on each event. (Keeps payload tiny; client owns rendering.)
   - Unknown path -> 404.
   - `argparse`: `--port` (default 8787), `--host` (default 127.0.0.1),
     `--no-open` (skip auto-opening the browser).
   - On start, prints the URL and (unless `--no-open`) opens it via
     `webbrowser.open`.

3. **`dashboard/index.html`** — single static page. Chart.js from CDN.
   - Controls: source toggle (Claude / agy), range picker (7d / 30d / all).
   - Charts: line chart of daily tokens (Claude) / daily sessions (agy), plus a
     stacked bar of model mix. A small "live" indicator that flips when an SSE
     refresh lands.
   - Vanilla JS `fetch` + `EventSource('/events')`. No build step.

4. **`agykit` (bash) — `cmd_dash`** — mirrors existing `cmd_*` style:
   ```bash
   cmd_dash() {
       local dir; dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dashboard"
       exec python3 "$dir/server.py" "$@"
   }
   ```
   - Add `dash) cmd_dash "${@:2}" ;;` to the dispatch `case`.
   - Add a `agykit dash [--port N]` line to `usage()`.

### Data flow

1. `agykit dash` -> execs `python3 server.py`.
2. Server starts, opens browser at `http://127.0.0.1:8787`.
3. Page loads `index.html`, opens `EventSource('/events')`, fetches
   `/api/data?source=claude&range=7d`.
4. Collectors read the local files, return series JSON; Chart.js renders.
5. Background: server watches file mtimes; on change pushes SSE `refresh`;
   client refetches and re-renders. Live.

### Error handling

- Missing `stats-cache.json` or empty `brain/` -> collector returns an empty
  series `{ labels: [], datasets: [] }` plus a `warning` field; the page shows
  "no data yet" rather than erroring.
- Malformed JSONL lines in agy transcripts -> skipped individually (counter of
  skipped lines surfaced in the `warning` field).
- Port already in use -> server prints a clear message and exits non-zero;
  `--port` lets the user pick another.
- SSE client disconnect -> handler exits its loop quietly (broken pipe caught).

### Testing

- `dashboard/` ships fixtures: a tiny fake `stats-cache.json` and a couple of
  synthetic `transcript_full.jsonl` files under a temp dir.
- `tests/` (pytest, stdlib + pytest only — pytest is dev-only):
  - `claude_series` parses fixture into expected daily buckets; respects range.
  - `agy_series` buckets sessions/tool-calls/model by date; skips malformed
    lines and reports the skip count.
  - Range filtering (`7d` / `30d` / `all`) returns the right label window.
  - A smoke test that boots the server on an ephemeral port, hits `/api/data`
    and `/`, asserts 200 + shape. (Uses `http.client`, no extra deps.)
- Existing agykit bash tests must still pass (sourcing guard unaffected — the
  new `cmd_dash` only runs on dispatch).

## File layout (new)

```
agykit/
  dashboard/
    server.py          # stdlib http server + SSE + routing
    collectors.py      # claude + agy series readers
    index.html         # Chart.js page
    fixtures/          # test data
  tests/
    test_collectors.py
    test_server.py
  docs/specs/2026-05-30-quota-dashboard-design.md   # this file
```

## Out of scope (phase 2+)

- True live "remaining quota %" gauge for agy (needs agykit run-hook that
  captures the statusline JSON or parses agy output into a usage log).
- Claude 5h / weekly subscription-limit gauge.
- Per-project breakdown, cost estimation in dollars, historical export.

## Decisions (confirmed with user)

1. Launched as a **subcommand** (`agykit dash`), not standalone/menubar/static.
2. **Live** refresh (SSE on file change).
3. agy shown as **activity** metrics (sessions / tool-calls / model) for v1;
   token/quota deferred.
4. Lives under the **agykit** project, zero pip dependencies (stdlib only).
