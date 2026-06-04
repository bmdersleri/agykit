import os
import re
import json
import socket
import sqlite3
import uuid
import sys
from datetime import datetime, timezone

from dashboard.state import resolve_job_state


# Lazy import: avoid circular dep when jobd.py loads this module
def _ensure_daemon():
    try:
        from dashboard.jobd import ensure_daemon

        # Don't check return value — best-effort start
        ensure_daemon()
    except Exception:
        pass


_STATE = resolve_job_state()
DB_PATH = _STATE["db_path"]
_OLD_JSON_DIR = _STATE["old_job_dir"]
_JOB_SOCKET = _STATE["socket_path"]
_ACTIVE_STATUSES = frozenset(
    {"starting", "running", "verifying", "rotating", "rolling_back"}
)
JOB_STALE_TIMEOUT = 300  # 5 minutes


def _pid_alive(pid) -> bool:
    """True if a process with this PID is currently running.

    do-escalate/run execute synchronously, so the agykit shell ($$) recorded as
    owner_pid IS the job's process. Its liveness — not event recency — is the
    ground truth for "is this job still running". A long, silent agy phase keeps
    the owner alive; a crashed/killed run leaves it dead. None/blank/garbage and
    a missing process all read as dead so callers can recover safely.
    """
    if pid is None or pid == "":
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:  # ESRCH — no such process
        return False
    except PermissionError:  # EPERM — exists but not ours
        return True
    except (OSError, OverflowError):  # bad/out-of-range pid → treat as dead
        return False


ERROR_CATEGORIES = {
    "quota": r"RESOURCE_EXHAUSTED|quota.*(?:reached|exceeded)|429.*quota|rate.*limit|403.*quota",
    "timeout": r"timeout|timed ?out",
    "network": r"ConnectionError|Connection refused|reset by peer|Name or service not known",
    "auth": r"unauthorized|invalid.*token|OAuth|permission.*denied|access_denied",
    "verify": r"verify.*fail|VERIFICATION FAILED",
}


def _classify_error(error_text: str | None) -> str | None:
    if not error_text:
        return None
    for category, pattern in ERROR_CATEGORIES.items():
        if re.search(pattern, error_text, re.IGNORECASE):
            return category
    return None


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    command     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'starting',
    stage       TEXT NOT NULL DEFAULT 'starting',
    account     TEXT,
    model       TEXT,
    prompt      TEXT DEFAULT '',
    started_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    ended_at    TEXT,
    last_error  TEXT,
    verify_result TEXT,
    diff_output TEXT,
    owner_pid   INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
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
"""


_PHASE3_COLUMNS = [
    ("duration_seconds", "REAL"),
    ("error_detail", "TEXT"),
    ("error_category", "TEXT"),
    ("diff_output", "TEXT"),
    ("owner_pid", "INTEGER"),
]


def _migrate_schema(conn: sqlite3.Connection):
    for col_name, col_type in _PHASE3_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    first = not os.path.isfile(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA_SQL)
    _migrate_schema(conn)
    if first and os.path.isdir(_OLD_JSON_DIR):
        _migrate_from_json(conn)
    return conn


def _migrate_from_json(conn: sqlite3.Connection):
    try:
        names = sorted(
            n
            for n in os.listdir(_OLD_JSON_DIR)
            if n.endswith(".json") and not n.endswith(".events.jsonl")
        )
    except Exception:
        return
    for name in names:
        job_id = name[:-5]
        snap_path = os.path.join(_OLD_JSON_DIR, name)
        events_path = os.path.join(_OLD_JSON_DIR, f"{job_id}.events.jsonl")
        try:
            with open(snap_path) as f:
                snap = json.load(f)
        except Exception:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO jobs
               (job_id, command, status, stage, account, model, prompt,
                started_at, updated_at, ended_at, last_error, verify_result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap.get("job_id", job_id),
                snap.get("command", "") or "",
                snap.get("status", "starting") or "starting",
                snap.get("stage", "starting") or "starting",
                snap.get("account"),
                snap.get("model"),
                snap.get("prompt", "") or "",
                snap.get("started_at", "") or "",
                snap.get("updated_at", "") or "",
                snap.get("ended_at"),
                snap.get("last_error"),
                snap.get("verify_result"),
            ),
        )
        if os.path.isfile(events_path):
            try:
                with open(events_path) as ef:
                    for line in ef:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        conn.execute(
                            """INSERT INTO events
                               (job_id, ts, event, status, stage, account, model, message, error)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                ev.get("job_id", job_id),
                                ev.get("ts", "") or "",
                                ev.get("event", "") or "",
                                ev.get("status", "") or "",
                                ev.get("stage", "") or "",
                                ev.get("account"),
                                ev.get("model"),
                                ev.get("message", "") or "",
                                ev.get("error"),
                            ),
                        )
            except Exception:
                pass
    conn.commit()


def _notify_socket(event_dict: dict):
    if not os.path.exists(_JOB_SOCKET):
        _ensure_daemon()
        # Wait briefly for daemon to bind
        for _ in range(5):
            if os.path.exists(_JOB_SOCKET):
                break
            import time

            time.sleep(0.3)
        else:
            return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.sendto(json.dumps(event_dict, default=str).encode("utf-8"), _JOB_SOCKET)
        s.close()
    except Exception:
        pass


def job_create(command: str, prompt: str = "", owner_pid: int | None = None) -> str:
    conn = _get_db()
    ts = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:6]
    job_id = f"{ts.strftime('%Y%m%dT%H%M%S')}-{suffix}"
    ts_iso = ts.isoformat()
    pid_val: int | None
    try:
        pid_val = int(owner_pid) if owner_pid not in (None, "") else None
    except (TypeError, ValueError):
        pid_val = None
    try:
        conn.execute(
            """INSERT INTO jobs
               (job_id, command, status, stage, prompt, started_at, updated_at, owner_pid)
               VALUES (?, ?, 'starting', 'starting', ?, ?, ?, ?)""",
            (job_id, command, prompt[:200], ts_iso, ts_iso, pid_val),
        )
        conn.execute(
            """INSERT INTO events
               (job_id, ts, event, status, stage, message)
               VALUES (?, ?, 'job_started', 'starting', 'starting', ?)""",
            (job_id, ts_iso, f"Job started: {command}"),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return job_id


def job_event(
    job_id: str,
    event_type: str,
    status: str,
    stage: str,
    account: str | None = None,
    model: str | None = None,
    message: str = "",
    error: str | None = None,
):
    conn = _get_db()
    ts = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """INSERT INTO events
               (job_id, ts, event, status, stage, account, model, message, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, ts, event_type, status, stage, account, model, message, error),
        )
        ended_at = ts if status in ("succeeded", "failed", "blocked") else None
        duration_seconds = None
        error_category = None
        if ended_at:
            row = conn.execute(
                "SELECT started_at FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row and row["started_at"]:
                try:
                    started = datetime.fromisoformat(row["started_at"])
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    duration_seconds = (
                        datetime.now(timezone.utc) - started
                    ).total_seconds()
                except Exception:
                    pass
            error_category = _classify_error(error)
        conn.execute(
            """UPDATE jobs SET
               status=?, stage=?, updated_at=?,
               account=COALESCE(?, account),
               model=COALESCE(?, model),
               last_error=COALESCE(?, last_error),
               ended_at=COALESCE(?, ended_at),
               duration_seconds=COALESCE(?, duration_seconds),
               error_detail=COALESCE(?, error_detail),
               error_category=COALESCE(?, error_category)
               WHERE job_id=?""",
            (
                status,
                stage,
                ts,
                account,
                model,
                error,
                ended_at,
                duration_seconds,
                error,
                error_category,
                job_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _notify_socket(
        {
            "job_id": job_id,
            "ts": ts,
            "event": event_type,
            "status": status,
            "stage": stage,
            "account": account,
            "model": model,
            "message": message,
            "error": error,
        }
    )
    if status in ("succeeded", "failed", "blocked"):
        try:
            from dashboard.notify import notify as _notify

            cmd = ""
            conn2 = _get_db()
            try:
                row = conn2.execute(
                    "SELECT command FROM jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if row:
                    cmd = row["command"]
            finally:
                conn2.close()
            summary = f"agykit job `{job_id[:12]}` *{status}* — {cmd[:60]}"
            if status == "failed":
                summary += f" | error: {message[:100]}" if message else " | error"
            _notify(job_id, status, summary)
        except Exception:
            pass


def job_snapshot(job_id: str) -> dict | None:
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def job_events(job_id: str, limit: int = 100) -> list[dict]:
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
        result = [dict(r) for r in rows]
        result.reverse()
        return result
    finally:
        conn.close()


def _parse_job_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


_TIMELINE_LABELS = {
    "job_started": "Started",
    "account_selected": "Account Selected",
    "account_switched": "Account Switched",
    "model_selected": "Model Selected",
    "model_escalated": "Model Escalated",
    "model_retried": "Model Retried",
    "prompt_dispatched": "Prompt Dispatched",
    "verify_started": "Verification Started",
    "verify_passed": "Verification Passed",
    "verify_failed": "Verification Failed",
    "quota_rotated": "Quota Rotated",
    "rollback_started": "Rollback Started",
    "rollback_finished": "Rollback Finished",
    "rollback_failed": "Rollback Failed",
    "job_succeeded": "Succeeded",
    "job_failed": "Failed",
    "job_blocked": "Blocked",
    "job_cancelled": "Cancelled",
    "job_timed_out": "Timed Out",
}


def _timeline_label(event_name: str) -> str:
    return _TIMELINE_LABELS.get(event_name, event_name.replace("_", " ").title())


def _timeline_status(event_name: str, snapshot_status: str, is_last: bool) -> str:
    if event_name in {
        "job_failed",
        "job_blocked",
        "job_cancelled",
        "job_timed_out",
        "verify_failed",
        "rollback_failed",
    }:
        return "failed"
    if is_last and snapshot_status in _ACTIVE_STATUSES:
        return "active"
    return "completed"


def _timeline_severity(event_name: str) -> str:
    if event_name in {"job_failed", "job_blocked", "job_cancelled", "job_timed_out"}:
        return "critical"
    if event_name in {"verify_failed", "rollback_started", "rollback_failed", "quota_rotated"}:
        return "warning"
    if event_name in {"job_succeeded", "verify_passed", "rollback_finished"}:
        return "success"
    return "info"


def job_timeline(job_id: str | None = None, limit: int = 100) -> dict:
    conn = _get_db()
    try:
        recover_stale_jobs(conn)
        if not job_id:
            row = conn.execute(
                """SELECT job_id FROM jobs
                   ORDER BY CASE WHEN status IN ('starting','running','verifying','rotating','rolling_back') THEN 0 ELSE 1 END,
                            updated_at DESC
                   LIMIT 1"""
            ).fetchone()
            if row:
                job_id = row["job_id"]
        if not job_id:
            return {
                "ok": True,
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "source": "agykit",
                "stale": False,
                "job_id": None,
                "snapshot": None,
                "timeline": [],
                "metrics": {
                    "elapsed_seconds": None,
                    "attempt_count": 0,
                    "model_switch_count": 0,
                    "account_switch_count": 0,
                    "rollback_count": 0,
                    "verify_fail_count": 0,
                },
                "warning": "No jobs found",
            }

        snapshot_row = conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if snapshot_row is None:
            return {
                "ok": True,
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "source": "agykit",
                "stale": False,
                "job_id": job_id,
                "snapshot": None,
                "timeline": [],
                "metrics": {
                    "elapsed_seconds": None,
                    "attempt_count": 0,
                    "model_switch_count": 0,
                    "account_switch_count": 0,
                    "rollback_count": 0,
                    "verify_fail_count": 0,
                },
                "warning": "Job not found",
            }

        snapshot = dict(snapshot_row)
        rows = conn.execute(
            "SELECT * FROM events WHERE job_id=? ORDER BY id ASC LIMIT ?",
            (job_id, limit),
        ).fetchall()
        events = [dict(r) for r in rows]

        started = _parse_job_iso(snapshot.get("started_at"))
        ended = _parse_job_iso(snapshot.get("ended_at"))
        now = datetime.now(timezone.utc)
        elapsed_seconds = None
        if started:
            elapsed_seconds = int(((ended or now) - started).total_seconds())

        timeline = []
        prev_ts = None
        last_account = None
        last_model = None
        account_switch_count = 0
        model_switch_count = 0
        rollback_count = 0
        verify_fail_count = 0
        attempt_count = 0

        for idx, event in enumerate(events, start=1):
            event_name = event.get("event", "")
            ts = _parse_job_iso(event.get("ts"))
            duration_ms = None
            if ts and prev_ts:
                duration_ms = int((ts - prev_ts).total_seconds() * 1000)
            if ts:
                prev_ts = ts
            if event_name == "job_started":
                attempt_count += 1
            if event_name in {"account_selected", "account_switched"} and event.get("account") != last_account:
                account_switch_count += 1
                last_account = event.get("account")
            if event_name in {"model_selected", "model_escalated", "model_retried"} and event.get("model") != last_model:
                model_switch_count += 1
                last_model = event.get("model")
            if event_name.startswith("rollback_"):
                rollback_count += 1
            if event_name == "verify_failed":
                verify_fail_count += 1

            timeline.append(
                {
                    "seq": idx,
                    "event": event_name,
                    "label": _timeline_label(event_name),
                    "timestamp": event.get("ts"),
                    "status": _timeline_status(event_name, snapshot.get("status", ""), idx == len(events)),
                    "severity": _timeline_severity(event_name),
                    "duration_ms": duration_ms,
                    "account": event.get("account"),
                    "model": event.get("model"),
                    "stage": event.get("stage"),
                    "message": event.get("message", ""),
                    "error": event.get("error"),
                }
            )

        if not attempt_count and events:
            attempt_count = 1

        return {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "source": "agykit",
            "stale": False,
            "job_id": job_id,
            "snapshot": snapshot,
            "timeline": timeline,
            "metrics": {
                "elapsed_seconds": elapsed_seconds,
                "attempt_count": attempt_count,
                "model_switch_count": model_switch_count,
                "account_switch_count": account_switch_count,
                "rollback_count": rollback_count,
                "verify_fail_count": verify_fail_count,
            },
            "warning": None,
        }
    finally:
        conn.close()


def recover_stale_jobs(conn: sqlite3.Connection, *, force: bool = False) -> list[dict]:
    """Reap active jobs that can no longer be running. Returns recovered rows.

    Canonical recovery shared by job_list/job_stats and the jobd daemon, so both
    use one semantic (``status='failed'``) instead of the old split where this
    module wrote ``blocked`` and the daemon wrote ``failed`` for the same case.

    Two independent reasons to reap an active job:

    * **timed_out** — ``started_at`` older than AGYKIT_JOB_TIMEOUT (default 1800s).
      A hard wall-clock ceiling, evaluated *regardless of PID*: the final
      backstop against a wedged or PID-recycled run.
    * **recovered (stale)** — no event for JOB_STALE_TIMEOUT (300s) *and the
      owning process is dead*. The PID gate is the fix for the core bug: a live
      do-escalate sits silent for minutes during agy's real work, so event
      recency alone wrongly flagged it complete. A live owner is never stale.

    ``force=True`` drops the 300s quiet-period gate but KEEPS the PID gate — it
    reaps dead-owner jobs immediately, never a live one (that's ``agykit cancel``).
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    raw_timeout = os.environ.get("AGYKIT_JOB_TIMEOUT", "1800")
    try:
        job_timeout = int(raw_timeout) if raw_timeout else 0
    except ValueError:
        job_timeout = 1800

    rows = conn.execute(
        """SELECT job_id, owner_pid, started_at, updated_at FROM jobs
           WHERE status IN ('starting','running','verifying','rotating','rolling_back')"""
    ).fetchall()

    stale_cutoff = (now - timedelta(seconds=JOB_STALE_TIMEOUT)).isoformat()
    timeout_cutoff = (
        (now - timedelta(seconds=job_timeout)).isoformat() if job_timeout > 0 else None
    )

    recovered: list[dict] = []
    for row in rows:
        jid = row["job_id"]
        pid = row["owner_pid"]
        started = row["started_at"] or ""
        updated = row["updated_at"] or ""

        is_timeout = timeout_cutoff is not None and started < timeout_cutoff
        is_stale = (
            (force or updated < stale_cutoff)
            and not _pid_alive(pid)
        )
        if not (is_timeout or is_stale):
            continue

        if is_timeout:
            event_type, stage = "job_timed_out", "timed_out"
            msg = f"Timed out after {job_timeout}s — reaped by agykit"
        else:
            event_type, stage = "job_blocked", "recovered"
            msg = f"Recovered — owner process gone, no activity for {JOB_STALE_TIMEOUT}s+"

        conn.execute(
            """INSERT INTO events
               (job_id, ts, event, status, stage, message)
               VALUES (?, ?, ?, 'failed', ?, ?)""",
            (jid, now_iso, event_type, stage, msg),
        )
        conn.execute(
            """UPDATE jobs SET status='failed', stage=?,
               updated_at=?, ended_at=?, last_error=? WHERE job_id=?""",
            (stage, now_iso, now_iso, msg, jid),
        )
        recovered.append({"job_id": jid, "owner_pid": pid, "stage": stage})

    if recovered:
        conn.commit()
    return recovered


# Back-compat alias: older call sites used the private name.
def _recover_stale_jobs(conn: sqlite3.Connection, force: bool = False) -> list[dict]:
    return recover_stale_jobs(conn, force=force)


def job_list(
    limit: int = 20,
    status: str | None = None,
    command: str | None = None,
    account: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    conn = _get_db()
    try:
        recover_stale_jobs(conn)
        _auto_prune_if_needed(conn)
        wheres: list[str] = []
        params: list = []
        if status:
            wheres.append("status = ?")
            params.append(status)
        if command:
            wheres.append("command = ?")
            params.append(command)
        if account:
            wheres.append("account = ?")
            params.append(account)
        if since:
            wheres.append("started_at >= ?")
            params.append(since)
        if until:
            wheres.append("started_at <= ?")
            params.append(until)
        where_clause = ""
        if wheres:
            where_clause = "WHERE " + " AND ".join(wheres)
        sql = f"SELECT * FROM jobs {where_clause} ORDER BY started_at DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def job_stats() -> dict:
    conn = _get_db()
    from datetime import datetime, timezone, timedelta

    try:
        recover_stale_jobs(conn)
        now = datetime.now(timezone.utc)
        total = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        by_status: dict[str, int] = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) AS c FROM jobs GROUP BY status"
        ).fetchall():
            by_status[row["status"]] = row["c"]

        since_24h = (now - timedelta(hours=24)).isoformat()
        recent = conn.execute(
            "SELECT status, COUNT(*) AS c FROM jobs WHERE started_at >= ? GROUP BY status",
            (since_24h,),
        ).fetchall()
        recent_by_status = {r["status"]: r["c"] for r in recent}
        recent_total = sum(recent_by_status.values())

        success_rate_24h = None
        terminal_24h = (
            recent_by_status.get("succeeded", 0)
            + recent_by_status.get("failed", 0)
            + recent_by_status.get("blocked", 0)
        )
        if terminal_24h > 0:
            success_rate_24h = round(
                recent_by_status.get("succeeded", 0) / terminal_24h * 100, 1
            )

        avg_dur_row = conn.execute(
            "SELECT AVG(duration_seconds) AS ad FROM jobs WHERE duration_seconds IS NOT NULL"
        ).fetchone()
        avg_duration_seconds = (
            round(avg_dur_row["ad"], 1) if avg_dur_row and avg_dur_row["ad"] else None
        )

        error_breakdown: dict[str, int] = {}
        for row in conn.execute(
            "SELECT error_category, COUNT(*) AS c FROM jobs WHERE error_category IS NOT NULL GROUP BY error_category"
        ).fetchall():
            error_breakdown[row["error_category"]] = row["c"]

        since_14d = (now - timedelta(days=14)).isoformat()
        daily = conn.execute(
            "SELECT DATE(started_at) AS day, COUNT(*) AS c FROM jobs WHERE started_at >= ? GROUP BY day ORDER BY day",
            (since_14d,),
        ).fetchall()
        daily_counts = {r["day"]: r["c"] for r in daily}

        return {
            "total": total,
            "by_status": by_status,
            "last_24h": {"total": recent_total, "by_status": recent_by_status},
            "success_rate_24h": success_rate_24h,
            "avg_duration_seconds": avg_duration_seconds,
            "error_breakdown": error_breakdown,
            "daily_counts": daily_counts,
        }
    finally:
        conn.close()


def job_cancel(job_id: str, message: str = ""):
    conn = _get_db()
    ts = datetime.now(timezone.utc).isoformat()
    msg = message or f"Cancelled by user"
    try:
        conn.execute(
            """INSERT INTO events
               (job_id, ts, event, status, stage, message)
               VALUES (?, ?, 'job_blocked', 'blocked', 'cancelled', ?)""",
            (job_id, ts, msg),
        )
        conn.execute(
            """UPDATE jobs SET status='blocked', stage='cancelled',
               updated_at=?, ended_at=? WHERE job_id=?""",
            (ts, ts, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _notify_socket(
        {
            "job_id": job_id,
            "ts": ts,
            "event": "job_blocked",
            "status": "blocked",
            "stage": "cancelled",
            "message": msg,
        }
    )


def job_prune(
    older_than_seconds: int = 0,
    status_filter: str | None = None,
    dry_run: bool = False,
    max_count: int = 0,
) -> int:
    """Delete jobs. Returns count of removed jobs.

    Args:
        older_than_seconds: remove jobs where started_at is older than now - N seconds.
                            If 0 and no other filter, remove all (subject to status_filter).
        status_filter:       optional status to filter by (e.g. 'succeeded').
        dry_run:             if True, only count matching jobs without deleting.
        max_count:           if > 0, keep only the most recent N jobs and prune the rest.
                             Ignored when older_than_seconds is also set (both apply).
    """
    conn = _get_db()
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    wheres: list[str] = []
    params: list = []

    if older_than_seconds > 0:
        cutoff = (now - timedelta(seconds=older_than_seconds)).isoformat()
        wheres.append("started_at < ?")
        params.append(cutoff)

    if status_filter:
        wheres.append("status = ?")
        params.append(status_filter)

    where_clause = " AND ".join(wheres) if wheres else "1=1"

    count_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM jobs WHERE {where_clause}", params
    ).fetchone()
    count = count_row["cnt"] if count_row else 0

    if dry_run:
        conn.close()
        return count

    deleted = 0
    if count > 0:
        conn.execute(
            f"DELETE FROM events WHERE job_id IN (SELECT job_id FROM jobs WHERE {where_clause})",
            params,
        )
        conn.execute(f"DELETE FROM jobs WHERE {where_clause}", params)
        conn.commit()
        deleted = count

    if max_count > 0:
        # Remove jobs beyond the max_count limit (oldest first)
        over = conn.execute(
            "SELECT COUNT(*) - ? AS over FROM jobs", (max_count,)
        ).fetchone()
        over_count = over["over"] if over else 0
        if over_count > 0:
            rows = conn.execute(
                "SELECT job_id FROM jobs ORDER BY started_at ASC LIMIT ?",
                (over_count,),
            ).fetchall()
            ids = tuple(r["job_id"] for r in rows)
            conn.execute(
                f"DELETE FROM events WHERE job_id IN ({','.join('?' * len(ids))})", ids
            )
            conn.execute(
                f"DELETE FROM jobs WHERE job_id IN ({','.join('?' * len(ids))})", ids
            )
            conn.commit()
            deleted += len(ids)

    conn.close()
    return deleted


def _auto_prune_if_needed(conn: sqlite3.Connection):
    import os
    from datetime import datetime, timezone, timedelta

    ttl_days = int(os.environ.get("AGYKIT_JOB_TTL_DAYS", "30"))
    max_jobs = int(os.environ.get("AGYKIT_JOB_MAX_COUNT", "500"))
    if ttl_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        conn.execute(
            "DELETE FROM events WHERE job_id IN (SELECT job_id FROM jobs WHERE started_at < ?)",
            (cutoff,),
        )
        conn.execute("DELETE FROM jobs WHERE started_at < ?", (cutoff,))
    if max_jobs > 0:
        over_row = conn.execute(
            "SELECT MAX(0, COUNT(*) - ?) AS over FROM jobs", (max_jobs,)
        ).fetchone()
        over = over_row["over"] if over_row else 0
        if over > 0:
            rows = conn.execute(
                "SELECT job_id FROM jobs ORDER BY started_at ASC LIMIT ?", (over,)
            ).fetchall()
            ids = tuple(r["job_id"] for r in rows)
            conn.execute(
                f"DELETE FROM events WHERE job_id IN ({','.join('?' * len(ids))})", ids
            )
            conn.execute(
                f"DELETE FROM jobs WHERE job_id IN ({','.join('?' * len(ids))})", ids
            )
    if ttl_days > 0 or max_jobs > 0:
        conn.commit()


def job_set_verify_result(job_id: str, result: str):
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE jobs SET verify_result=? WHERE job_id=?",
            (result, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def job_set_diff(job_id: str, diff: str):
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE jobs SET diff_output=? WHERE job_id=?",
            (diff, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
