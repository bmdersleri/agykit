import datetime
import json
import os
import sqlite3
from collections import deque


_CODEX_HOME = "~/.codex"


def _epoch_label(ts: int | float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _short_project(path: str) -> str:
    return os.path.basename(path.rstrip(os.sep)) if path else ""


def _read_recent_prompts(path: str, limit: int) -> tuple[list[dict], int, str | None]:
    if not os.path.isfile(path):
        return [], 0, f"Codex history not found: {path}"

    total = 0
    skipped = 0
    window: deque = deque(maxlen=limit)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                total += 1
                window.append(item)
    except Exception as e:
        return [], 0, f"Cannot read Codex history: {e}"

    prompts = []
    for item in window:
        ts = int(item.get("ts") or 0)
        prompts.append({
            "session_id": item.get("session_id", ""),
            "timestamp": ts,
            "display_time": _epoch_label(ts),
            "text": item.get("text", ""),
        })
    prompts.sort(key=lambda x: x["timestamp"], reverse=True)

    warning = f"Skipped {skipped} malformed Codex history line(s)" if skipped else None
    return prompts, total, warning


def _read_recent_sessions(path: str, limit: int) -> tuple[list[dict], str | None]:
    if not os.path.isfile(path):
        return [], f"Codex session index not found: {path}"

    window: deque = deque(maxlen=limit)
    skipped = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    window.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
    except Exception as e:
        return [], f"Cannot read Codex session index: {e}"

    sessions = []
    for item in window:
        updated = item.get("updated_at") or ""
        ts_epoch = 0
        if updated:
            try:
                ts_epoch = int(
                    datetime.datetime.fromisoformat(
                        updated.replace("Z", "+00:00")
                    ).timestamp()
                )
            except Exception:
                ts_epoch = 0
        sessions.append({
            "id": item.get("id", ""),
            "thread_name": item.get("thread_name", ""),
            "updated_at": updated,
            "ts_epoch": ts_epoch,
        })
    sessions.sort(key=lambda x: x["ts_epoch"], reverse=True)

    warning = f"Skipped {skipped} malformed Codex session line(s)" if skipped else None
    return sessions, warning


def _read_thread_stats(path: str, project_path: str, limit: int) -> tuple[dict, dict, list[dict], str | None]:
    empty_summary = {
        "sessions": 0,
        "tokens_used": 0,
        "models": [],
        "last_activity": "",
    }
    empty_project = {
        "path": project_path,
        "name": _short_project(project_path),
        "sessions": 0,
        "tokens_used": 0,
    }
    if not os.path.isfile(path):
        return empty_summary, empty_project, [], f"Codex state DB not found: {path}"

    try:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, title, cwd, tokens_used, model, updated_at
            FROM threads
            WHERE archived = 0
            ORDER BY updated_at DESC
            """
        ).fetchall()
        con.close()
    except Exception as e:
        return empty_summary, empty_project, [], f"Cannot read Codex state DB: {e}"

    models = sorted({
        row["model"] for row in rows
        if row["model"] and row["model"] != "auto"
    })
    tokens = sum(int(row["tokens_used"] or 0) for row in rows)
    last_ts = int(rows[0]["updated_at"] or 0) if rows else 0
    summary = {
        "sessions": len(rows),
        "tokens_used": tokens,
        "models": models,
        "last_activity": _epoch_label(last_ts),
    }

    project_rows = [
        row for row in rows
        if os.path.abspath(row["cwd"] or "") == os.path.abspath(project_path)
    ]
    project = {
        "path": project_path,
        "name": _short_project(project_path),
        "sessions": len(project_rows),
        "tokens_used": sum(int(row["tokens_used"] or 0) for row in project_rows),
    }

    recent_threads = []
    for row in rows[:limit]:
        recent_threads.append({
            "id": row["id"],
            "title": row["title"] or "",
            "project": _short_project(row["cwd"] or ""),
            "model": row["model"] or "",
            "tokens_used": int(row["tokens_used"] or 0),
            "updated_at": _epoch_label(row["updated_at"]),
        })

    return summary, project, recent_threads, None


def codex_usage(
    limit: int = 20,
    *,
    codex_home: str | None = None,
    history_path: str | None = None,
    session_index_path: str | None = None,
    state_path: str | None = None,
    project_path: str | None = None,
) -> dict:
    """Return local Codex activity stats from ~/.codex without reading auth data."""
    home = os.path.expanduser(
        codex_home or os.environ.get("AGYKIT_DASH_CODEX_HOME") or _CODEX_HOME
    )
    history = os.path.expanduser(
        history_path or os.environ.get("AGYKIT_DASH_CODEX_HISTORY")
        or os.path.join(home, "history.jsonl")
    )
    session_index = os.path.expanduser(
        session_index_path or os.environ.get("AGYKIT_DASH_CODEX_SESSION_INDEX")
        or os.path.join(home, "session_index.jsonl")
    )
    state = os.path.expanduser(
        state_path or os.environ.get("AGYKIT_DASH_CODEX_STATE")
        or os.path.join(home, "state_5.sqlite")
    )
    project = os.path.abspath(
        project_path or os.environ.get("AGYKIT_DASH_CODEX_PROJECT") or os.getcwd()
    )

    warnings = []
    recent_prompts, prompt_total, warning = _read_recent_prompts(history, limit)
    if warning:
        warnings.append(warning)

    indexed_sessions, warning = _read_recent_sessions(session_index, limit)
    if warning:
        warnings.append(warning)

    summary, current_project, recent_threads, warning = _read_thread_stats(
        state, project, limit
    )
    if warning:
        warnings.append(warning)

    summary["prompts"] = prompt_total
    available = bool(prompt_total or summary["sessions"] or indexed_sessions)

    return {
        "available": available,
        "summary": summary,
        "current_project": current_project,
        "recent_prompts": recent_prompts,
        "recent_threads": recent_threads,
        "indexed_sessions": indexed_sessions,
        "warning": " | ".join(warnings) if warnings and not available else None,
    }
