# Job Observability — Advanced Roadmap

**Date:** 2026-06-01
**Status:** Draft
**Audience:** agykit maintainers

This document extends the initial job observability feature
(`docs/plans/2026-06-01-agykit-live-job-observability-plan.md`) into a
multi-phase hardening roadmap. Each phase is self-contained, backwards
compatible, and delivers value independently.

---

## Overview

The current implementation uses JSON snapshot + JSONL event log files in
`~/.gemini/agykit-jobs/`. It works, but has known limitations:

| Limitation | Impact |
|---|---|
| No concurrent-write protection | Race if two agykit processes write simultaneously |
| Polling-based `watch` | 2-second latency, unnecessary CPU |
| No stale job detection | Orphaned "running" jobs after Ctrl+C or crash |
| No pruning | Jobs accumulate forever |
| Flat file storage | No indexing, aggregation, or efficient search |
| No cancellation | User cannot stop a hung job gracefully |

The roadmap below addresses each limitation in logical phases.

---

## Phase 1 — Store Migration: JSON → SQLite

**Goal:** Atomic, concurrent-safe, queryable storage.

### Design

Replace the flat JSON/JSONL files with a single SQLite database at
`~/.gemini/agykit-jobs.db`.

#### Schema

```sql
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    command     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'starting',
    stage       TEXT NOT NULL DEFAULT 'starting',
    account     TEXT,
    model       TEXT,
    prompt      TEXT,
    started_at  TEXT NOT NULL,       -- ISO 8601
    updated_at  TEXT NOT NULL,
    ended_at    TEXT,
    last_error  TEXT,
    verify_result TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(job_id),
    ts          TEXT NOT NULL,
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    account     TEXT,
    model       TEXT,
    message     TEXT DEFAULT '',
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_events_ts     ON events(ts);
CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_started  ON jobs(started_at);
```

#### WAL Mode

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

WAL mode allows concurrent reads + one writer without locks.

### Migration Path

- A `migrate_v1_to_v2()` function reads `~/.gemini/agykit-jobs/*.json` +
  `*.events.jsonl` and populates the SQLite database.
- Keep the old path as a fallback for one release.
- Remove old file-based code in the following release.

### New / Changed Functions

| Function | Change |
|---|---|
| `job_create()` | INSERT INTO jobs, INSERT INTO events |
| `job_event()`  | UPDATE jobs + INSERT INTO events (atomic via transaction) |
| `job_snapshot()` | SELECT * FROM jobs WHERE job_id = ? |
| `job_events()` | SELECT * FROM events WHERE job_id = ? ORDER BY id |
| `job_list()`   | SELECT * FROM jobs ORDER BY started_at DESC LIMIT ? |
| `job_count(status, since)` | New: SELECT COUNT(*) with filters |

### Files to touch

- `dashboard/collectors/jobs.py` — rewrite storage layer, keep same public API
- `dashboard/collectors/__init__.py` — unchanged (same exports)
- `agykit` — unchanged (calls same Python functions)
- `tests/test_collectors.py` — update existing tests + add SQLite-specific tests

### Backwards Compatibility

- Old JSON/JSONL files are not deleted unless migration succeeds.
- If `~/.gemini/agykit-jobs/` exists but DB does not, migrate silently on first
  call to any job function.
- The `_ops_log` (legacy ops log) is untouched — it continues to exist alongside
  the new system.

### Verification

```bash
python3 -m pytest tests/test_collectors.py -q -k "job"
```

All existing job tests must pass unchanged. Add 5 new tests:

1. Concurrent write from two threads
2. Migration from JSON files
3. Query by status filter
4. Query by time range
5. Database file created at expected path

---

## Phase 2 — Real-Time Event Bus: Unix Socket + inotify

**Goal:** Zero-latency event delivery without polling.

### Design

1. A **Unix domain socket** (`~/.gemini/agykit-jobs.sock`) acts as a pub/sub
   endpoint.
2. When `job_event()` is called, after writing to SQLite, it also serialises
   the event as a JSON line and writes it to the socket (non-blocking).
3. `agykit watch <job-id>` connects to the socket and prints events as they
   arrive. No polling loop — it blocks on `recv()`.
4. If no listener is connected (`connect()` fails or `send()` returns EAGAIN),
   the write is silently dropped — zero overhead.
5. The dashboard SSE endpoint (`/events`) also connects to the socket, so the
   browser gets push updates without polling the SQLite DB.

### Socket Lifecycle

- Socket file is created on first `job_event()` call if any listener socket
  has been created.
- Cleanup: register `atexit` handler to unlink the socket.
- Lister starts the socket server in a daemon thread.

### `agykit watch` — Rework

- Remove the 2-second `time.sleep()` loop.
- Instead: listen on the Unix socket for events matching the given `job_id`.
- Fallback: if socket is unavailable, poll SQLite every second (degraded mode).

### `agykit tail` (new)

```bash
agykit tail <job-id>      # live event stream (socket, fallback to poll)
agykit tail --all          # all jobs, all events
agykit tail --status failed # filter by status
```

Output format (tail mode):

```
12:00:01  job_started       starting          Job started: run
12:00:05  account_selected  running           Switched to user@example.com
12:01:30  job_succeeded     done              Success on user@example.com
```

### Files to touch

- `dashboard/collectors/jobs.py` — add socket pub logic, thread lifecycle
- `agykit` — rewrite `cmd_job_watch` and add `cmd_job_tail`
- `dashboard/server.py` — wire SSE into the event socket (opt-in)
- `web/app.js` — no change needed (already uses SSE)

### Verification

```bash
# Terminal 1
agykit run "hello" &
agykit watch <job-id>
# Events should appear in real time, no perceptible delay
```

```bash
# Terminal 2 (degraded mode)
rm -f ~/.gemini/agykit-jobs.sock
agykit watch <job-id>
# Should fall back to 1-second SQLite polling
```

---

## Phase 3 — Heartbeat, Stale Detection & Crash Recovery

**Goal:** Detect orphan jobs and recover automatically.

### Heartbeat Mechanism

Every `job_event()` call updates `jobs.updated_at`. A background check runs:

- On every `job_list()` call, also check for stale jobs.
- A job is **stale** when:
  - `status IN ('starting', 'running', 'verifying', 'rotating', 'rolling_back')`
  - AND `updated_at` is older than `JOB_STALE_TIMEOUT` (default: 5 minutes)
- Stale jobs automatically get a `job_blocked` event and status set to `blocked`.

### Signal Handling in Bash

Add `trap` handlers to `cmd_run()` and `cmd_do_escalate()` in `agykit`:

```bash
_job_cleanup() {
    [ -n "${_CURRENT_JOB_ID:-}" ] && {
        _job_op event "$_CURRENT_JOB_ID" "job_blocked" "blocked" "interrupted" \
            "" "" "Process interrupted (SIGINT/SIGTERM)"
    }
}
trap _job_cleanup EXIT INT TERM
```

Set `_CURRENT_JOB_ID` at job creation time so the trap can reference it.

### `agykit cancel` (new)

```bash
agykit cancel <job-id>     # Set status → "blocked" with event `job_blocked`
agykit cancel --all        # Cancel all running/starting/verifying jobs
```

Implementation: simply calls `job_event(job_id, "job_blocked", "blocked", ...)`.

### Recovery on Start

On `agykit jobs` or `agykit status`, scan for stale jobs and auto-recover:

```python
def _recover_stale_jobs():
    stale = job_list(status_filter=ACTIVE_STATUSES, max_age_minutes=5)
    for j in stale:
        job_event(j["job_id"], "job_blocked", "blocked", "recovered",
                  message="Marked stale — no activity for 5+ minutes")
```

This runs lazily (not on a timer), so there is zero ongoing cost.

### Files to touch

- `dashboard/collectors/jobs.py` — stale detection + recovery
- `agykit` — trap handlers in `cmd_run` / `cmd_do_escalate`, new `cmd_job_cancel`
- `tests/test_collectors.py` — stale detection test

### Verification

```bash
# Simulate an orphaned job
python3 -c "
from dashboard.collectors.jobs import job_create
from datetime import datetime, timezone
job_id = job_create('run', 'orphan')
# Manually set updated_at to 10 minutes ago
import sqlite3
# (internal — test helper does this via monkeypatch)
"

agykit jobs   # Should show the job as "blocked" with event "recovered"
```

---

## Phase 4 — Housekeeping: Prune & TTL

**Goal:** Prevent disk bloat.

### `agykit prune` (new)

```bash
agykit prune --older-than 7d     # Remove jobs older than 7 days
agykit prune --status succeeded  # Remove only successful jobs
agykit prune --dry-run           # Show what would be deleted
agykit prune --all               # Remove everything (respects --dry-run)
```

### Auto-Pruning Policy

Configurable via `.agykit.conf` or env var:

```bash
AGYKIT_JOB_TTL_DAYS=30           # Default: keep 30 days
AGYKIT_JOB_MAX_COUNT=500         # Default: keep last 500 jobs
```

On every `job_list()` call, if the DB size exceeds thresholds, auto-prune the
oldest jobs in a background thread.

### Files to touch

- `dashboard/collectors/jobs.py` — `job_prune()` function + auto-prune hook
- `agykit` — `cmd_job_prune` dispatch

### Verification

```bash
agykit jobs | wc -l
agykit prune --older-than 0s --dry-run   # Should list all jobs
agykit prune --older-than 0s             # Delete all
agykit jobs | wc -l                      # Should be 0 (or 1 if a new one was created)
```

---

## Phase 5 — Filtering, Search & JSON Output

**Goal:** Make job data scriptable and queryable.

### Enhanced `agykit jobs`

```bash
agykit jobs --status failed            # Filter by status
agykit jobs --command run               # Filter by command
agykit jobs --account user@example.com  # Filter by account
agykit jobs --since 24h                 # Time range
agykit jobs --json                      # Machine-readable JSON
agykit jobs --limit 100                 # Override default limit
```

### Implementation

Add an optional `filters` dict parameter to `job_list()`:

```python
def job_list(
    limit: int = 20,
    status: str | list[str] | None = None,
    command: str | None = None,
    account: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]: ...
```

The SQLite query is built dynamically with WHERE clauses. When the old JSON
storage is still in use, filtering falls back to post-filtering in Python.

### `agykit stats` (new)

```bash
agykit stats           # Summary: total jobs, by status, last 24h
```

Output:

```
Jobs total: 142
  succeeded:  98
  failed:     32
  running:     2
  blocked:    10

Last 24h: 12 jobs (8 succeeded, 3 failed, 1 running)
```

### Files to touch

- `dashboard/collectors/jobs.py` — filter params, `job_stats()` function
- `agykit` — enhanced `cmd_jobs`, new `cmd_job_stats`

### Verification

```bash
agykit jobs --status failed --since 1h --json | jq '. | length'
# Expected: number of failed jobs in the last hour
```

---

## Phase 6 — Terminal UI for `agykit watch`

**Goal:** Rich, real-time terminal dashboard.

### Design

Replace the plain `clear + print` loop with a **Textual** TUI application.
Textual is a Python framework for terminal UIs (similar to Rich but interactive).

```python
# dashboard/tui.py — optional, import-error friendly
try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Static, DataTable
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False
```

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  agykit Job Monitor                  ● live             │
├─────────────────────────────────────────────────────────┤
│  Job: 20260601T120000-a1b2c3   Status: running          │
│  Cmd:  do-escalate "fix quota"  Stage: verifying…       │
│  Acct: user@example.com         Model: Gemini Pro       │
│  Elapsed: 3m 42s                                        │
├─────────────────────────────────────────────────────────┤
│  Events                                                   │
│  12:00:01  job_started       starting                    │
│  12:00:05  account_selected  running   user@example.com  │
│  12:00:30  model_selected    running   Gemini Pro        │
│  12:01:30  verify_started    verifying …                  │
│  …                                                        │
├─────────────────────────────────────────────────────────┤
│  F1:Help  F2:Filter  q:quit                              │
└─────────────────────────────────────────────────────────┘
```

### Fallback

If Textual is not installed, `agykit watch` uses the current simple polling
implementation. No new dependency required.

### Files to touch

- `dashboard/tui.py` — new optional TUI module
- `agykit` — try Textual, fallback to simple watch

### Verification

```bash
pip install textual   # optional
agykit watch <job-id>
# See rich TUI
```

---

## Phase 7 — Notifications & Webhooks

**Goal:** Push notifications on job completion.

### Design

On `job_succeeded` / `job_failed` / `job_blocked` events, check for configured
notification channels:

```python
import os, json, urllib.request

_NOTIFY_CHANNELS = {
    "slack":   os.environ.get("AGYKIT_JOB_SLACK_WEBHOOK"),
    "telegram": os.environ.get("AGYKIT_JOB_TELEGRAM_TOKEN"),
    "ntfy":     os.environ.get("AGYKIT_JOB_NTFY_TOPIC"),
}

def _notify(job_id, status, summary):
    for channel, config in _NOTIFY_CHANNELS.items():
        if not config:
            continue
        if channel == "slack":
            _notify_slack(config, job_id, status, summary)
        elif channel == "telegram":
            _notify_telegram(config, job_id, status, summary)
        # …
```

### Call Site

Add `_notify()` call in `job_event()` only for terminal statuses:

```python
if status in ("succeeded", "failed", "blocked"):
    _notify(job_id, status, message)
```

### Configuration

Via `.agykit.conf` or env vars:

```bash
AGYKIT_JOB_SLACK_WEBHOOK="https://hooks.slack.com/services/…"
AGYKIT_JOB_TELEGRAM_TOKEN="bot12345:token"
AGYKIT_JOB_TELEGRAM_CHAT_ID="-1001234567890"
AGYKIT_JOB_NTFY_TOPIC="agykit-alerts"
```

### Files to touch

- `dashboard/collectors/jobs.py` — notification dispatch
- `dashboard/notify.py` — new module, one function per channel

### Verification

```bash
export AGYKIT_JOB_NTFY_TOPIC="agykit-test"
agykit run "hello"
# Should receive a ntfy.sh/agykit-test notification
```

---

## Phase 8 — Dashboard v2: Job Detail View

**Goal:** Full job browsing and inspection from the browser.

### UI

- New page at `http://localhost:8787/jobs.html` or an in-app tab
- Job list with clickable rows: status badge, command, stage, account, elapsed
- Click a row → detail view with full event timeline, error context, verify result
- Live updates via SSE for in-progress jobs

### API additions

| Endpoint | Response |
|---|---|
| `GET /api/jobs?status=failed&since=24h` | Filtered job list |
| `GET /api/jobs/stats` | Summary stats (total, by status, last 24h) |
| `GET /api/jobs/<id>/events?after=N` | New events since event ID N (for live scroll) |

### Files to touch

- `dashboard/server.py` — new endpoints
- `web/jobs.html` — new page
- `web/jobs.js` — new JS module
- `web/style.css` — job detail styles

---

## Implementation Sequence

```
Phase  ───  Effort  ───  Risk  ───  Value  ───  Dependency
────────────────────────────────────────────────────────────
  1       3-4 days     medium    high       none
  2       2-3 days     low       high       Phase 1
  3       1-2 days     low       high       Phase 1
  4       1 day        low       medium     Phase 1
  5       2-3 days     low       medium     Phase 1
  6       4-5 days     medium    medium     Phase 2
  7       1-2 days     low       low        none
  8       3-4 days     low       medium     Phase 1
────────────────────────────────────────────────────────────
Total:   ~18 days
```

**Recommended start:** Phase 1 (SQLite) — it unlocks everything else and is
fully backwards compatible.

---

## Hard Constraints (from AGENTS.md)

- **stdlib only** for core functionality. Textual (Phase 6) and webhook HTTP
  clients (Phase 7) are optional — they degrade gracefully when not installed.
- **No new runtime dependencies** — Phase 1, 2, 3, 4, 5 use only `sqlite3`,
  `socket`, `os`, `json`, `threading` from stdlib.
- **Bind to 127.0.0.1 only** — Dashboard already does this.

## Appendix: Comparison

| Metric | Current (JSON) | Phase 1 (SQLite) |
|---|---|---|
| Concurrent writes | Race-prone | Atomic (WAL) |
| Query by status | O(n) scan | O(log n) index |
| Query by time | O(n) scan | O(log n) index |
| Disk space | Redundant JSON+JSONL | Single DB |
| Migration cost | — | One-time, automatic |
| Tooling | cat, grep, jq | sqlite3 CLI, any SQL client |
