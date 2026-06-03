import os
import sys
import socket
import json
import time
import uuid
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dashboard.jobd as jd

from dashboard.jobd import (
    JobDaemon,
    daemon_status,
    daemon_stop,
    ensure_daemon,
)

TEST_DIR = "/tmp/agykit-jobd-test"


@pytest.fixture(autouse=True)
def test_env():
    uid = uuid.uuid4().hex[:8]
    db_path = os.path.join(TEST_DIR, f"agykit-jobs-{uid}.db")
    sock_path = os.path.join(TEST_DIR, f"agykit-jobs-{uid}.sock")
    pid_file = os.path.join(TEST_DIR, f"agykit-jobd-{uid}.pid")

    jd.DB_PATH = db_path
    jd.SOCK_PATH = sock_path
    jd.PID_FILE = pid_file
    jd.DAEMON_DIR = TEST_DIR

    # Also patch collectors jobs module's DB_PATH
    import dashboard.collectors.jobs as cj

    cj.DB_PATH = db_path
    cj._JOB_SOCKET = sock_path

    os.makedirs(TEST_DIR, exist_ok=True)
    for p in [pid_file, sock_path, db_path, db_path + "-wal", db_path + "-shm"]:
        try:
            os.unlink(p)
        except OSError:
            pass
    yield
    for p in [pid_file, sock_path, db_path, db_path + "-wal", db_path + "-shm"]:
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
    time.sleep(1)
    status = daemon_status()
    assert status["running"] is True
    assert status["pid"] is not None
    assert os.path.isfile(jd.PID_FILE)
    assert os.path.exists(jd.SOCK_PATH)

    stopped = daemon_stop()
    assert stopped is True
    time.sleep(1)
    assert daemon_status()["running"] is False


def test_daemon_socket_broadcast():
    assert ensure_daemon()
    time.sleep(1)

    watcher_path = jd.SOCK_PATH + f".{os.getpid()}.watch"
    watcher = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    watcher.settimeout(2.0)
    watcher.bind(watcher_path)

    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    event = {
        "job_id": "test-001",
        "event": "job_started",
        "status": "starting",
        "stage": "starting",
    }
    sender.sendto(json.dumps(event).encode("utf-8"), jd.SOCK_PATH)
    sender.close()

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
    assert ensure_daemon() is True
    pid2 = daemon_status()["pid"]
    assert pid2 == pid1
    daemon_stop()


def test_daemon_recover_stale_jobs():
    os.environ["AGYKIT_JOB_TIMEOUT"] = ""  # disable timeout for this test
    from datetime import datetime, timezone

    conn = jd._get_db()
    old_ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (job_id, command, status, stage, started_at, updated_at) "
        "VALUES (?, ?, 'running', 'running', ?, ?)",
        ("stale-test", "test", old_ts, old_ts),
    )
    conn.commit()
    conn.close()

    d = JobDaemon()
    d._recover_stale_jobs()

    conn2 = jd._get_db()
    row = conn2.execute(
        "SELECT status, stage FROM jobs WHERE job_id=?", ("stale-test",)
    ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "recovered"
    conn2.close()
    del os.environ["AGYKIT_JOB_TIMEOUT"]


def test_socket_notify_auto_starts_daemon():
    from dashboard.collectors.jobs import _notify_socket, _JOB_SOCKET
    import dashboard.collectors.jobs as cj

    cj._JOB_SOCKET = jd.SOCK_PATH
    assert daemon_status()["running"] is False
    _notify_socket({"job_id": "auto-test", "event": "test"})
    time.sleep(2)
    status = daemon_status()
    assert status["running"] is True
    daemon_stop()


def test_daemon_timeout_auto_cancel():
    os.environ["AGYKIT_JOB_TIMEOUT"] = "1"
    d = JobDaemon()
    from datetime import datetime, timezone, timedelta

    conn = jd._get_db()
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO jobs (job_id, command, status, stage, started_at, updated_at) "
        "VALUES (?, ?, 'running', 'running', ?, ?)",
        ("timeout-test-001", "test-timeout", old_ts, old_ts),
    )
    conn.commit()
    conn.close()

    d._recover_stale_jobs()

    conn2 = jd._get_db()
    row = conn2.execute(
        "SELECT status, stage, last_error FROM jobs WHERE job_id=?",
        ("timeout-test-001",),
    ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "timed_out"
    assert "Timed out" in (row[2] or "")
    conn2.close()
    del os.environ["AGYKIT_JOB_TIMEOUT"]


def test_can_start_job_no_active():
    from dashboard.collectors.jobs import job_list, _ACTIVE_STATUSES

    active = [j for j in job_list(limit=50) if j.get("status") in _ACTIVE_STATUSES]
    assert isinstance(active, list)
