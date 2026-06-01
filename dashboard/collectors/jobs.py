import os
import json
import uuid
from datetime import datetime, timezone

JOBS_DIR = os.path.expanduser("~/.gemini/agykit-jobs")


def _ensure_dir():
    os.makedirs(JOBS_DIR, exist_ok=True)


def _job_path(job_id):
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def _events_path(job_id):
    return os.path.join(JOBS_DIR, f"{job_id}.events.jsonl")


def job_create(command: str, prompt: str = "") -> str:
    _ensure_dir()
    ts = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:6]
    job_id = f"{ts.strftime('%Y%m%dT%H%M%S')}-{suffix}"

    snapshot = {
        "job_id": job_id,
        "command": command,
        "status": "starting",
        "stage": "starting",
        "account": None,
        "model": None,
        "prompt": prompt[:200],
        "started_at": ts.isoformat(),
        "updated_at": ts.isoformat(),
        "ended_at": None,
        "last_error": None,
        "verify_result": None,
    }

    with open(_job_path(job_id), "w") as f:
        json.dump(snapshot, f, indent=2)

    _write_event(job_id, {
        "job_id": job_id,
        "ts": ts.isoformat(),
        "event": "job_started",
        "status": "starting",
        "stage": "starting",
        "account": None,
        "model": None,
        "message": f"Job started: {command}",
    })

    return job_id


def job_event(job_id: str, event_type: str, status: str, stage: str,
              account: str | None = None, model: str | None = None,
              message: str = "", error: str | None = None):
    _ensure_dir()
    ts = datetime.now(timezone.utc)
    event = {
        "job_id": job_id,
        "ts": ts.isoformat(),
        "event": event_type,
        "status": status,
        "stage": stage,
        "account": account,
        "model": model,
        "message": message,
    }
    if error is not None:
        event["error"] = error

    _write_event(job_id, event)
    _update_snapshot(job_id, status, stage, account, model, error)


def _write_event(job_id, event):
    path = _events_path(job_id)
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def _update_snapshot(job_id, status, stage, account=None, model=None, error=None):
    snap_path = _job_path(job_id)
    if not os.path.exists(snap_path):
        return
    try:
        with open(snap_path) as f:
            snap = json.load(f)
        snap["status"] = status
        snap["stage"] = stage
        snap["updated_at"] = datetime.now(timezone.utc).isoformat()
        if account:
            snap["account"] = account
        if model:
            snap["model"] = model
        if error:
            snap["last_error"] = error
        if status in ("succeeded", "failed", "blocked"):
            snap["ended_at"] = datetime.now(timezone.utc).isoformat()
        with open(snap_path, "w") as f:
            json.dump(snap, f, indent=2)
    except Exception:
        pass


def job_snapshot(job_id: str) -> dict | None:
    path = _job_path(job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def job_events(job_id: str, limit: int = 100) -> list[dict]:
    path = _events_path(job_id)
    if not os.path.isfile(path):
        return []
    result = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return result[-limit:]


def job_list(limit: int = 20) -> list[dict]:
    _ensure_dir()
    entries = []
    try:
        for name in os.listdir(JOBS_DIR):
            if not name.endswith(".json") or name.endswith(".events.jsonl"):
                continue
            try:
                with open(os.path.join(JOBS_DIR, name)) as f:
                    entries.append(json.load(f))
            except Exception:
                pass
        entries.sort(
            key=lambda j: j.get("started_at", ""),
            reverse=True
        )
        entries = entries[:limit]
    except Exception:
        pass
    return entries


def job_set_verify_result(job_id: str, result: str):
    snap_path = _job_path(job_id)
    if not os.path.exists(snap_path):
        return
    try:
        with open(snap_path) as f:
            snap = json.load(f)
        snap["verify_result"] = result
        with open(snap_path, "w") as f:
            json.dump(snap, f, indent=2)
    except Exception:
        pass
