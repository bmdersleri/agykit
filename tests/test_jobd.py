import os
import sys
import socket
import json
import time
import signal
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.jobd import (
    JobDaemon,
    daemon_status,
    daemon_stop,
    ensure_daemon,
    PID_FILE,
    SOCK_PATH,
    DB_PATH,
)

# Use temp paths for testing
TEST_DIR = "/tmp/agykit-jobd-test"


@pytest.fixture(autouse=True)
def test_env():
    os.environ["HOME"] = TEST_DIR
    os.environ["XDG_CONFIG_HOME"] = TEST_DIR
    os.makedirs(TEST_DIR, exist_ok=True)
    # Clean up any leftover state
    for p in [PID_FILE, SOCK_PATH, DB_PATH]:
        try:
            os.unlink(p)
        except OSError:
            pass
    yield
    for p in [PID_FILE, SOCK_PATH, DB_PATH]:
        try:
            os.unlink(p)
        except OSError:
            pass


def test_daemon_status_when_not_running():
    status = daemon_status()
    assert status["running"] is False
    assert status["pid"] is None


def test_daemon_start_stop():
    assert daemon_status()["running"] is False
    ok = ensure_daemon()
    assert ok is True
    # Give it a moment
    time.sleep(1)
    status = daemon_status()
    assert status["running"] is True
    assert status["pid"] is not None
    assert os.path.isfile(PID_FILE)
    assert os.path.exists(SOCK_PATH)

    stopped = daemon_stop()
    assert stopped is True
    time.sleep(1)
    assert daemon_status()["running"] is False


def test_daemon_socket_broadcast():
    assert ensure_daemon()
    time.sleep(1)

    # Create a watcher socket
    watcher_path = SOCK_PATH + f".{os.getpid()}.watch"
    watcher = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    watcher.settimeout(2.0)
    watcher.bind(watcher_path)

    # Send an event via the daemon's socket
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    event = {"job_id": "test-001", "event": "job_started", "status": "starting", "stage": "starting"}
    sender.sendto(json.dumps(event).encode("utf-8"), SOCK_PATH)
    sender.close()

    # Watcher should receive it
    data, _ = watcher.recvfrom(4096)
    received = json.loads(data.decode("utf-8"))
    assert received["job_id"] == "test-001"
    assert received["event"] == "job_started"

    watcher.close()
    daemon_stop()
    time.sleep(0.5)


def test_daemon_prevents_duplicate():
    assert ensure_daemon()
    time.sleep(1)
    pid1 = daemon_status()["pid"]

    # Starting again should fail silently — PID file locked
    assert ensure_daemon() is True
    pid2 = daemon_status()["pid"]
    assert pid2 == pid1

    daemon_stop()


def test_daemon_recover_stale_jobs():
    """Stale recovery should mark old active jobs as blocked."""
    import sqlite3
    from datetime import datetime, timezone

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'starting',
            stage TEXT NOT NULL DEFAULT 'starting',
            account TEXT,
            model TEXT,
            prompt TEXT DEFAULT '',
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            ended_at TEXT,
            last_error TEXT,
            verify_result TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            ts TEXT NOT NULL,
            event TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            account TEXT,
            model TEXT,
            message TEXT DEFAULT '',
            error TEXT
        );
    """)
    old_ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (job_id, command, status, stage, started_at, updated_at) VALUES (?, ?, 'running', 'running', ?, ?)",
        ("stale-test", "test", old_ts, old_ts),
    )
    conn.commit()
    conn.close()

    from dashboard.jobd import JobDaemon
    d = JobDaemon()
    d._recover_stale_jobs()

    conn2 = sqlite3.connect(DB_PATH, timeout=5)
    row = conn2.execute(
        "SELECT status, stage FROM jobs WHERE job_id=?", ("stale-test",)
    ).fetchone()
    assert row is not None
    assert row[0] == "blocked"
    assert row[1] == "recovered"
    conn2.close()


def test_socket_notify_auto_starts_daemon():
    """_notify_socket in jobs.py should auto-start the daemon."""
    from dashboard.collectors.jobs import _notify_socket
    assert daemon_status()["running"] is False
    _notify_socket({"job_id": "auto-test", "event": "test"})
    time.sleep(1.5)
    # Daemon should have been started
    status = daemon_status()
    assert status["running"] is True
    daemon_stop()
