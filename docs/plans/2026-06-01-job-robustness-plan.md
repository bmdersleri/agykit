# Job Management Robustness — Implementation Plan

**Date:** 2026-06-01
**Status:** Draft

## Current Architecture

```
bash cmd_run / cmd_do_escalate
  └─ _job_op (Python subprocess)
       └─ dashboard.collectors.jobs
            ├─ SQLite (WAL) — ~/.gemini/agykit-jobs.db
            │   ├─ jobs (job_id, command, status, stage, account, model, ...)
            │   └─ events (id, job_id, ts, event, status, stage, message, error)
            └─ _notify_socket() — Unix DGRAM broadcast
```

### Known Gaps

| # | Gap | Severity |
|---|-----|----------|
| 1 | No persistent daemon — socket messages lost when nobody listens | High |
| 2 | No job-level timeout — zombie jobs stay "running" forever | High |
| 3 | No concurrency guard — simultaneous jobs corrupt account state | High |
| 4 | Error context truncated to 200 chars | Medium |
| 5 | No duration tracking — no analytics possible | Medium |
| 6 | Socket cleanup unreliable under SIGKILL | Low |
| 7 | No retry on transient errors | Low |
| 8 | No error taxonomy — string-based, no categorization | Low |

## Phases

---

### Phase 1 — Background Daemon + Socket Reliability

**Goal:** Persistent event listener + reliable socket communication.

**Files:**
- `dashboard/jobd.py` (new) — daemon process
- `dashboard/collectors/jobs.py` — update `_notify_socket` + add daemon helper
- `tests/test_jobd.py` (new) — daemon tests

**jobd.py design:**

```
jobd.py ── daemon lifecycle:
  ┌─────────────────────────────┐
  │ start()                     │
  │  ├─ PID file lock (~/.gemini/agykit-jobd.pid)   │
  │  ├─ Signal handlers (SIGTERM, SIGINT → cleanup)  │
  │  ├─ Socket bind (~/.gemini/agykit-jobs.sock)     │
  │  ├─ Heartbeat thread (10s interval)               │
  │  │   └─ _recover_stale_jobs()                    │
  │  └─ Event loop (select → process → broadcast)    │
  └─────────────────────────────┘
```

Key behaviors:
- PID file with `fcntl.flock` to prevent multiple daemons
- Socket `SOCK_DGRAM` bind — persistent, survives daemon restarts
- Heartbeat runs `_recover_stale_jobs` every 10s
- Cleanup: unlink socket + PID file on shutdown
- `start()` is blocking; `stop()` via signal or call

**Bash integration:**
- `cmd_run` / `cmd_do_escalate` auto-start daemon if not running
- `agykit jobd start|stop|status` commands
- `agykit init` → add `AGYKIT_JOB_TIMEOUT` to `.agykit.conf`

---

### Phase 2 — Job Timeout + Concurrency Lock

**Goal:** No zombie jobs, no simultaneous job conflicts.

**Schema migration (jobs table):**
```sql
ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER DEFAULT 1800;
```

**Daemon heartbeat adds:**
```python
for row in conn.execute("SELECT job_id FROM jobs WHERE status IN (_ACTIVE_STATUSES) AND ..."):
    if now - started_at > timeout:
        job_event(job_id, "job_timed_out", "failed", "timed_out", ...)
```

**Concurrency guard in bash:**
```bash
_can_start_job() {
    local repo=$(_cmd_job_repo)
    PYTHONPATH="$repo" python3 -c "
from dashboard.collectors.jobs import job_list
active = [j for j in job_list(limit=50) if j['status'] in _ACTIVE_STATUSES]
if active:
    print(f'WARNING: {len(active)} job(s) still active', file=sys.stderr)
    for j in active: print(f'  {j[\"job_id\"]}  {j[\"command\"]}', file=sys.stderr)
    sys.exit(1)
"
}
```

- `--force` flag bypasses check
- `agykit run --force "prompt"`

---

### Phase 3 — Full Error Storage + Duration Tracking

**Goal:** Complete debug context + analytics foundation.

**Schema migration:**
```sql
ALTER TABLE jobs ADD COLUMN duration_seconds REAL;
ALTER TABLE jobs ADD COLUMN error_detail TEXT;
ALTER TABLE jobs ADD COLUMN error_category TEXT;
```

**Changes:**
- `job_event` sets `duration_seconds` = `(now - started_at).total_seconds()` on terminal events
- `cmd_do_escalate` stores full `vout` (not truncated) to `error_detail`
- `job_list` / `job_stats` expose duration fields
- Dashboard cards show duration + full error on click

**Error taxonomy:**
```python
ERROR_CATEGORIES = {
    "quota":   r"RESOURCE_EXHAUSTED|quota.*reached|429.*quota|rate.*limit",
    "timeout": r"timeout|timed ?out",
    "network": r"ConnectionError|Connection refused|reset by peer|Name or service not known",
    "auth":    r"unauthorized|invalid.*token|OAuth|permission.*denied",
    "verify":  r"verify.*fail|VERIFICATION FAILED",
}
```

---

### Phase 4 — Retry + Dashboard Analytics

**Goal:** Self-healing on transient errors + data-driven insights.

**Retry with backoff:**
```python
# In cmd_run / cmd_do_escalate:
for attempt in range(3):
    try:
        run()
        break
    except TransientError:
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        raise
```

**Retry categories:** network errors, timeout (not quota)

**Dashboard additions:**
- Job success rate card (%)
- Average duration per model/command
- Error breakdown by category
- Job timeline chart (daily count)

---

## Migration Strategy

All schema changes use `ALTER TABLE ADD COLUMN` — backward compatible.
The daemon handles both old and new schema versions.

## Rollback

```bash
mv ~/.gemini/agykit-jobs.db ~/.gemini/agykit-jobs.db.bak  # full backup
git revert <commit>
```

---

## Test Plan

| Phase | Tests |
|-------|-------|
| 1 | Daemon start/stop, socket broadcast with/without daemon, stale recovery via heartbeat |
| 2 | Timeout triggers auto-cancel, concurrency check blocks second job, `--force` bypasses |
| 3 | Duration populated on terminal events, verify error stored uncut, error_category classified |
| 4 | Retry succeeds on simulated transient error, dashboard loads with new fields |

```bash
python3 -m pytest tests/ -q
bash tests/test_git_safety.sh
```
