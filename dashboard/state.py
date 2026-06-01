import getpass
import os
import shutil
import sqlite3
import tempfile

PRIMARY_STATE_DIR = os.path.expanduser("~/.gemini")
STATE_DIR_ENV = "AGYKIT_STATE_DIR"
JOB_DB_NAME = "agykit-jobs.db"
JOB_SOCKET_NAME = "agykit-jobs.sock"
JOB_PID_NAME = "agykit-jobd.pid"
OLD_JOB_DIR_NAME = "agykit-jobs"

_STATE_CACHE: dict[str, str] | None = None


def _fallback_state_dir() -> str:
    user = os.getuid() if hasattr(os, "getuid") else getpass.getuser()
    return os.path.join(tempfile.gettempdir(), f"agykit-{user}")


def _candidate_state_dirs() -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get(STATE_DIR_ENV)
    if env_dir:
        candidates.append(os.path.expanduser(env_dir))
    candidates.append(PRIMARY_STATE_DIR)
    fallback = _fallback_state_dir()
    if fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _copy_job_bundle(source_dir: str, target_dir: str):
    if not os.path.isdir(source_dir) or os.path.abspath(source_dir) == os.path.abspath(target_dir):
        return

    os.makedirs(target_dir, exist_ok=True)

    source_db = os.path.join(source_dir, JOB_DB_NAME)
    target_db = os.path.join(target_dir, JOB_DB_NAME)
    for suffix in ("", "-wal", "-shm", "-journal"):
        src = source_db + suffix
        if os.path.exists(src):
            shutil.copy2(src, target_db + suffix)

    source_old = os.path.join(source_dir, OLD_JOB_DIR_NAME)
    target_old = os.path.join(target_dir, OLD_JOB_DIR_NAME)
    if os.path.isdir(source_old) and not os.path.exists(target_old):
        shutil.copytree(source_old, target_old, dirs_exist_ok=True)


def _probe_sqlite_path(db_path: str) -> bool:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("SELECT 1")
        conn.close()
        return True
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def resolve_job_state() -> dict[str, str]:
    global _STATE_CACHE
    if _STATE_CACHE is not None:
        return dict(_STATE_CACHE)

    for state_dir in _candidate_state_dirs():
        db_path = os.path.join(state_dir, JOB_DB_NAME)
        socket_path = os.path.join(state_dir, JOB_SOCKET_NAME)
        pid_file = os.path.join(state_dir, JOB_PID_NAME)

        if state_dir != PRIMARY_STATE_DIR and os.path.exists(os.path.join(PRIMARY_STATE_DIR, JOB_DB_NAME)):
            try:
                _copy_job_bundle(PRIMARY_STATE_DIR, state_dir)
            except OSError:
                pass

        if _probe_sqlite_path(db_path):
            _STATE_CACHE = {
                "state_dir": state_dir,
                "db_path": db_path,
                "socket_path": socket_path,
                "pid_file": pid_file,
                "old_job_dir": os.path.join(state_dir, OLD_JOB_DIR_NAME),
            }
            return dict(_STATE_CACHE)

    fallback_dir = _fallback_state_dir()
    try:
        _copy_job_bundle(PRIMARY_STATE_DIR, fallback_dir)
    except OSError:
        pass
    _STATE_CACHE = {
        "state_dir": fallback_dir,
        "db_path": os.path.join(fallback_dir, JOB_DB_NAME),
        "socket_path": os.path.join(fallback_dir, JOB_SOCKET_NAME),
        "pid_file": os.path.join(fallback_dir, JOB_PID_NAME),
        "old_job_dir": os.path.join(fallback_dir, OLD_JOB_DIR_NAME),
    }
    return dict(_STATE_CACHE)
