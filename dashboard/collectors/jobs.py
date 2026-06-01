import os
import json
import socket
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.gemini/agykit-jobs.db")
_OLD_JSON_DIR = os.path.expanduser("~/.gemini/agykit-jobs")
_JOB_SOCKET = os.path.expanduser("~/.gemini/agykit-jobs.sock")
_ACTIVE_STATUSES = frozenset({"starting", "running", "verifying", "rotating", "rolling_back"})
JOB_STALE_TIMEOUT = 300  # 5 minutes

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
    verify_result TEXT
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


def _get_db() -> sqlite3.Connection:
    first = not os.path.isfile(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA_SQL)
    if first and os.path.isdir(_OLD_JSON_DIR):
        _migrate_from_json(conn)
    return conn


def _migrate_from_json(conn: sqlite3.Connection):
    try:
        names = sorted(
            n for n in os.listdir(_OLD_JSON_DIR)
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
        return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.sendto(json.dumps(event_dict, default=str).encode("utf-8"), _JOB_SOCKET)
        s.close()
    except Exception:
        pass


def job_create(command: str, prompt: str = "") -> str:
    conn = _get_db()
    ts = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:6]
    job_id = f"{ts.strftime('%Y%m%dT%H%M%S')}-{suffix}"
    ts_iso = ts.isoformat()
    try:
        conn.execute(
            """INSERT INTO jobs
               (job_id, command, status, stage, prompt, started_at, updated_at)
               VALUES (?, ?, 'starting', 'starting', ?, ?, ?)""",
            (job_id, command, prompt[:200], ts_iso, ts_iso),
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


def job_event(job_id: str, event_type: str, status: str, stage: str,
              account: str | None = None, model: str | None = None,
              message: str = "", error: str | None = None):
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
        conn.execute(
            """UPDATE jobs SET
               status=?, stage=?, updated_at=?,
               account=COALESCE(?, account),
               model=COALESCE(?, model),
               last_error=COALESCE(?, last_error),
               ended_at=COALESCE(?, ended_at)
               WHERE job_id=?""",
            (status, stage, ts, account, model, error, ended_at, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _notify_socket({
        "job_id": job_id, "ts": ts, "event": event_type,
        "status": status, "stage": stage,
        "account": account, "model": model,
        "message": message, "error": error,
    })


def job_snapshot(job_id: str) -> dict | None:
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
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


def _recover_stale_jobs(conn: sqlite3.Connection, force: bool = False):
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=JOB_STALE_TIMEOUT)).isoformat()
    if force:
        cutoff = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        """SELECT job_id, command FROM jobs
           WHERE status IN ('starting','running','verifying','rotating','rolling_back')
           AND updated_at < ?""",
        (cutoff,),
    ).fetchall()
    for row in rows:
        jid = row["job_id"]
        conn.execute(
            """INSERT INTO events
               (job_id, ts, event, status, stage, message)
               VALUES (?, ?, 'job_blocked', 'blocked', 'recovered', ?)""",
            (jid, cutoff, f"Marked stale — no activity for {JOB_STALE_TIMEOUT}s+"),
        )
        conn.execute(
            """UPDATE jobs SET status='blocked', stage='recovered',
               updated_at=?, ended_at=? WHERE job_id=?""",
            (cutoff, cutoff, jid),
        )
    if rows:
        conn.commit()


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
        _recover_stale_jobs(conn)
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
    try:
        _recover_stale_jobs(conn)
        total = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        by_status: dict[str, int] = {}
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall():
            by_status[row["status"]] = row["c"]
        from datetime import datetime, timezone, timedelta
        since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        recent = conn.execute(
            "SELECT status, COUNT(*) AS c FROM jobs WHERE started_at >= ? GROUP BY status",
            (since_24h,),
        ).fetchall()
        recent_by_status = {r["status"]: r["c"] for r in recent}
        recent_total = sum(recent_by_status.values())
        return {
            "total": total,
            "by_status": by_status,
            "last_24h": {"total": recent_total, "by_status": recent_by_status},
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
    _notify_socket({
        "job_id": job_id, "ts": ts, "event": "job_blocked",
        "status": "blocked", "stage": "cancelled",
        "message": msg,
    })


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
        conn.execute(
            f"DELETE FROM jobs WHERE {where_clause}", params
        )
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
        conn.execute("DELETE FROM events WHERE job_id IN (SELECT job_id FROM jobs WHERE started_at < ?)", (cutoff,))
        conn.execute("DELETE FROM jobs WHERE started_at < ?", (cutoff,))
    if max_jobs > 0:
        over_row = conn.execute("SELECT MAX(0, COUNT(*) - ?) AS over FROM jobs", (max_jobs,)).fetchone()
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
