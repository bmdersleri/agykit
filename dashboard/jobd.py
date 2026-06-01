import os
import sys
import json
import signal
import socket
import select
import time
import fcntl
import sqlite3
from datetime import datetime, timezone, timedelta

DAEMON_DIR = os.path.expanduser("~/.gemini")
PID_FILE = os.path.join(DAEMON_DIR, "agykit-jobd.pid")
SOCK_PATH = os.path.expanduser("~/.gemini/agykit-jobs.sock")
DB_PATH = os.path.expanduser("~/.gemini/agykit-jobs.db")
HEARTBEAT_INTERVAL = 10
STALE_TIMEOUT = 300

_JOB_SCHEMA = """
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

_ACTIVE_STATUSES = frozenset(
    {"starting", "running", "verifying", "rotating", "rolling_back"}
)


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_JOB_SCHEMA)
    return conn


class JobDaemon:
    def __init__(self):
        self._running = False
        self._sock: socket.socket | None = None
        self._pid_fd: int | None = None

    def _lock_pidfile(self) -> bool:
        os.makedirs(DAEMON_DIR, exist_ok=True)
        fd = os.open(PID_FILE, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            existing = open(PID_FILE).read().strip()
            print(f"Daemon already running (PID {existing})", file=sys.stderr)
            return False
        os.write(fd, str(os.getpid()).encode())
        self._pid_fd = fd
        return True

    def _unlock_pidfile(self):
        if self._pid_fd is not None:
            try:
                fcntl.flock(self._pid_fd, fcntl.LOCK_UN)
                os.close(self._pid_fd)
            except OSError:
                pass
            self._pid_fd = None
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass

    def _bind_socket(self) -> bool:
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.settimeout(None)
        try:
            self._sock.bind(SOCK_PATH)
        except OSError as e:
            print(f"Cannot bind socket: {e}", file=sys.stderr)
            return False
        os.chmod(SOCK_PATH, 0o777)
        return True

    def _cleanup(self):
        self._unlock_pidfile()
        if self._sock is not None:
            try:
                os.unlink(SOCK_PATH)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _recover_stale_jobs(self):
        conn = _get_db()
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            stale_cutoff = (now - timedelta(seconds=STALE_TIMEOUT)).isoformat()
            stale_rows = conn.execute(
                """SELECT job_id, command FROM jobs
                   WHERE status IN ('starting','running','verifying','rotating','rolling_back')
                   AND updated_at < ?""",
                (stale_cutoff,),
            ).fetchall()

            raw_timeout = os.environ.get("AGYKIT_JOB_TIMEOUT", "1800")
            job_timeout = int(raw_timeout) if raw_timeout else 0
            timed_out_rows = []
            if job_timeout > 0:
                timeout_cutoff = (now - timedelta(seconds=job_timeout)).isoformat()
                timed_out_rows = conn.execute(
                    """SELECT job_id, command FROM jobs
                       WHERE status IN ('running','verifying','rotating','rolling_back')
                       AND started_at < ?""",
                    (timeout_cutoff,),
                ).fetchall()

            rows = stale_rows + [
                r for r in timed_out_rows
                if r["job_id"] not in {x["job_id"] for x in stale_rows}
            ]

            if not rows:
                return
            for row in rows:
                jid = row["job_id"]
                is_timeout = row["job_id"] in {x["job_id"] for x in timed_out_rows}
                if is_timeout:
                    event_type = "job_timed_out"
                    stage = "timed_out"
                    msg = f"Timed out after {job_timeout}s — cancelled by daemon"
                else:
                    event_type = "job_blocked"
                    stage = "recovered"
                    msg = f"Recovered by daemon — no activity for {STALE_TIMEOUT}s+"
                conn.execute(
                    """INSERT INTO events
                       (job_id, ts, event, status, stage, message)
                       VALUES (?, ?, ?, 'failed', ?, ?)""",
                    (jid, now_iso, event_type, stage, msg),
                )
                conn.execute(
                    """UPDATE jobs SET status='failed', stage=?,
                       updated_at=?, ended_at=?, last_error=?
                       WHERE job_id=?""",
                    (stage, now_iso, now_iso, msg, jid),
                )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    def _handle_signal(self, signum, frame):
        self._running = False

    def start(self):
        if not self._lock_pidfile():
            sys.exit(1)
        if not self._bind_socket():
            self._unlock_pidfile()
            sys.exit(1)

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGHUP, self._handle_signal)

        self._running = True
        last_heartbeat = 0.0

        while self._running:
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                try:
                    self._recover_stale_jobs()
                except Exception:
                    pass
                last_heartbeat = now

            r, _, _ = select.select([self._sock], [], [], 1.0)
            if not r:
                continue
            try:
                data, _ = self._sock.recvfrom(65535)
                if data:
                    event = json.loads(data.decode("utf-8"))
                    self._persist_and_broadcast(event)
            except (json.JSONDecodeError, OSError):
                pass

        self._cleanup()

    def _persist_and_broadcast(self, event: dict):
        event_type = event.get("event", "")
        status = event.get("status", "")
        self._notify_watchers(event)

    def _notify_watchers(self, event: dict):
        data = json.dumps(event, default=str).encode("utf-8")
        base = SOCK_PATH
        watch_dir = os.path.dirname(base)
        try:
            for entry in os.listdir(watch_dir):
                if entry.startswith(os.path.basename(base) + ".") and "watch" in entry:
                    path = os.path.join(watch_dir, entry)
                    try:
                        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                        s.settimeout(0.5)
                        s.sendto(data, path)
                        s.close()
                    except OSError:
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
        except OSError:
            pass


def daemon_status() -> dict:
    if not os.path.isfile(PID_FILE):
        return {"running": False, "pid": None}
    try:
        pid = int(open(PID_FILE).read().strip())
        os.kill(pid, 0)
        return {"running": True, "pid": pid}
    except (ValueError, OSError):
        return {"running": False, "pid": None}


def daemon_stop():
    status = daemon_status()
    if not status["running"]:
        print("Daemon not running.", file=sys.stderr)
        return False
    try:
        os.kill(status["pid"], signal.SIGTERM)
    except OSError:
        pass
    for _ in range(20):
        time.sleep(0.3)
        s = daemon_status()
        if not s["running"] and not os.path.isfile(PID_FILE):
            print(f"Daemon (PID {status['pid']}) stopped.")
            return True
    print(f"Daemon (PID {status['pid']}) may still be stopping...", file=sys.stderr)
    return True


def ensure_daemon() -> bool:
    status = daemon_status()
    if status["running"]:
        return True
    pid = os.fork()
    if pid == 0:
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
        daemon = JobDaemon()
        daemon.start()
        os._exit(0)
    for _ in range(10):
        time.sleep(0.3)
        if daemon_status()["running"]:
            return True
    return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "start":
            if daemon_status()["running"]:
                print("Daemon already running.")
                sys.exit(0)
            pid = os.fork()
            if pid == 0:
                os.setsid()
                devnull = os.open(os.devnull, os.O_RDWR)
                os.dup2(devnull, 0)
                os.dup2(devnull, 1)
                os.dup2(devnull, 2)
                os.close(devnull)
                d = JobDaemon()
                d.start()
                os._exit(0)
            for _ in range(5):
                time.sleep(0.5)
                if daemon_status()["running"]:
                    print(f"Daemon started (PID {daemon_status()['pid']}).")
                    sys.exit(0)
            print("Daemon failed to start.", file=sys.stderr)
            sys.exit(1)
        elif cmd == "stop":
            daemon_stop()
        elif cmd == "status":
            s = daemon_status()
            if s["running"]:
                print(f"running (PID {s['pid']})")
            else:
                print("stopped")
        else:
            print(f"Usage: {sys.argv[0]} start|stop|status", file=sys.stderr)
            sys.exit(1)
    else:
        d = JobDaemon()
        d.start()
