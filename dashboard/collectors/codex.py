import base64
import datetime
import glob
import json
import os
import select
import sqlite3
import subprocess
import time
from collections import deque


_CODEX_HOME = "~/.codex"
_QUOTA_WINDOW_SECONDS = 5 * 3600  # ChatGPT Plus: 5-hour rolling window


def _fetch_codex_rate_limits(timeout: float = 5.0) -> dict | None:
    """Query live rate-limit data from the Codex app-server via stdio JSON-RPC.

    Returns a dict with keys from RateLimitSnapshot (primary, secondary, planType,
    limitId, credits) or None on failure.
    """
    _INIT = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "agykit-dashboard", "version": "1.0"},
            "capabilities": {},
        },
    }
    _READ = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "account/rateLimits/read",
        "params": {},
    }

    try:
        proc = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return None

    try:
        proc.stdin.write(json.dumps(_INIT) + "\n")
        proc.stdin.flush()
        time.sleep(0.2)
        proc.stdin.write(json.dumps(_READ) + "\n")
        proc.stdin.flush()

        deadline = time.time() + timeout
        while time.time() < deadline:
            ready = select.select([proc.stdout], [], [], 0.1)[0]
            if not ready:
                continue
            line = proc.stdout.readline().strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                result = msg.get("result", {})
                # Prefer multi-bucket view keyed by limit_id if present
                by_id = result.get("rateLimitsByLimitId") or {}
                snapshot = by_id.get("codex") or result.get("rateLimits") or {}
                return snapshot if snapshot else None
    except Exception:
        return None
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            pass

    return None


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
        prompts.append(
            {
                "session_id": item.get("session_id", ""),
                "timestamp": ts,
                "display_time": _epoch_label(ts),
                "text": item.get("text", ""),
            }
        )
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
        sessions.append(
            {
                "id": item.get("id", ""),
                "thread_name": item.get("thread_name", ""),
                "updated_at": updated,
                "ts_epoch": ts_epoch,
            }
        )
    sessions.sort(key=lambda x: x["ts_epoch"], reverse=True)

    warning = f"Skipped {skipped} malformed Codex session line(s)" if skipped else None
    return sessions, warning


def _read_thread_stats(
    path: str, project_path: str, limit: int
) -> tuple[dict, dict, list[dict], str | None]:
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

    models = sorted(
        {row["model"] for row in rows if row["model"] and row["model"] != "auto"}
    )
    tokens = sum(int(row["tokens_used"] or 0) for row in rows)
    last_ts = int(rows[0]["updated_at"] or 0) if rows else 0
    summary = {
        "sessions": len(rows),
        "tokens_used": tokens,
        "models": models,
        "last_activity": _epoch_label(last_ts),
    }

    project_rows = [
        row
        for row in rows
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
        recent_threads.append(
            {
                "id": row["id"],
                "title": row["title"] or "",
                "project": _short_project(row["cwd"] or ""),
                "model": row["model"] or "",
                "tokens_used": int(row["tokens_used"] or 0),
                "updated_at": _epoch_label(row["updated_at"]),
            }
        )

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
        history_path
        or os.environ.get("AGYKIT_DASH_CODEX_HISTORY")
        or os.path.join(home, "history.jsonl")
    )
    session_index = os.path.expanduser(
        session_index_path
        or os.environ.get("AGYKIT_DASH_CODEX_SESSION_INDEX")
        or os.path.join(home, "session_index.jsonl")
    )
    state = os.path.expanduser(
        state_path
        or os.environ.get("AGYKIT_DASH_CODEX_STATE")
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

    plan_info = None
    auth_path = os.path.join(home, "auth.json")
    if os.path.isfile(auth_path):
        try:
            with open(auth_path) as f:
                auth_data = json.load(f)
            token = auth_data.get("tokens", {}).get("access_token", "")
            if token:
                payload = _decode_jwt_payload(token)
                if payload:
                    ad = payload.get("https://api.openai.com/auth", {})
                    profile = payload.get("https://api.openai.com/profile", {})
                    plan_info = {
                        "email": profile.get("email", ""),
                        "plan_type": ad.get("chatgpt_plan_type", ""),
                        "subscription_active_until": ad.get(
                            "chatgpt_subscription_active_until", ""
                        ),
                    }
        except Exception:
            pass

    return {
        "available": available,
        "summary": summary,
        "current_project": current_project,
        "recent_prompts": recent_prompts,
        "recent_threads": recent_threads,
        "indexed_sessions": indexed_sessions,
        "plan": plan_info,
        "warning": " | ".join(warnings) if warnings and not available else None,
    }


def _decode_jwt_payload(token: str) -> dict | None:
    """Decode a JWT token's payload without verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def _read_5h_token_usage(sessions_dir: str) -> dict:
    """Scan rollout JSONL files to compute 5-hour rolling token usage.

    Falls back to the most recent session outside the window if none are found
    inside the window, so the dashboard always shows something useful.

    Returns a dict with keys:
      - sessions: int  (number of sessions in window)
      - total_tokens: int
      - input_tokens: int
      - cached_input_tokens: int
      - output_tokens: int
      - window_seconds: int
      - window_start_ts: int (unix timestamp)
      - in_window: bool  (False = fallback to latest session outside window)
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = now - datetime.timedelta(seconds=_QUOTA_WINDOW_SECONDS)
    window_start_ts = int(window_start.timestamp())

    result = {
        "sessions": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "window_seconds": _QUOTA_WINDOW_SECONDS,
        "window_start_ts": window_start_ts,
        "in_window": True,
    }

    if not os.path.isdir(sessions_dir):
        return result

    pattern = os.path.join(sessions_dir, "**", "*.jsonl")
    try:
        files = glob.glob(pattern, recursive=True)
    except Exception:
        return result

    # Sort by mtime descending so we can find the most recent outside-window
    # session quickly for the fallback.
    files.sort(
        key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True
    )

    # --- Pass 1: collect all sessions in the 5-hour window ---
    # Pre-filter: skip files older than window_start - 2h (mtime slack).
    mtime_cutoff = window_start_ts - 7200

    def _extract_session(
        path: str,
    ) -> tuple[bool, datetime.datetime | None, dict | None]:
        """Return (session_in_window, session_start, last_token_count)."""
        last_tok: dict | None = None
        session_start: datetime.datetime | None = None
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if session_start is None and obj.get("type") == "session_meta":
                        ts_str = obj.get("payload", {}).get("timestamp", "")
                        if ts_str:
                            try:
                                session_start = datetime.datetime.fromisoformat(
                                    ts_str.replace("Z", "+00:00")
                                )
                            except Exception:
                                pass
                    if obj.get("type") == "event_msg":
                        p = obj.get("payload", {})
                        if p.get("type") == "token_count":
                            usage = p.get("info", {}).get("total_token_usage", {})
                            if usage:
                                last_tok = usage
        except Exception:
            pass
        in_win = session_start is not None and session_start >= window_start
        return in_win, session_start, last_tok

    best_fallback_ts: datetime.datetime | None = None
    best_fallback_tok: dict | None = None

    for f in files:
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        if mt < mtime_cutoff:
            # Files beyond the 2h slack are too old even for fallback
            break

        in_win, sess_ts, last_tok = _extract_session(f)

        if in_win and last_tok:
            result["sessions"] += 1
            result["total_tokens"] += int(last_tok.get("total_tokens", 0))
            result["input_tokens"] += int(last_tok.get("input_tokens", 0))
            result["cached_input_tokens"] += int(last_tok.get("cached_input_tokens", 0))
            result["output_tokens"] += int(last_tok.get("output_tokens", 0))
        elif (
            not in_win
            and last_tok
            and sess_ts is not None
            and (best_fallback_ts is None or sess_ts > best_fallback_ts)
        ):
            best_fallback_ts = sess_ts
            best_fallback_tok = last_tok

    # --- Fallback: show latest session even if outside window ---
    if result["sessions"] == 0 and best_fallback_tok:
        result["in_window"] = False
        result["sessions"] = 1
        result["total_tokens"] = int(best_fallback_tok.get("total_tokens", 0))
        result["input_tokens"] = int(best_fallback_tok.get("input_tokens", 0))
        result["cached_input_tokens"] = int(
            best_fallback_tok.get("cached_input_tokens", 0)
        )
        result["output_tokens"] = int(best_fallback_tok.get("output_tokens", 0))
        if best_fallback_ts:
            result["window_start_ts"] = int(best_fallback_ts.timestamp())

    return result


def codex_status(
    *,
    codex_home: str | None = None,
    auth_path: str | None = None,
    state_path: str | None = None,
) -> dict:
    """Return Codex account status info (plan type, model, usage) from local files.

    Returns:
        dict with keys:
          - available: bool
          - account: dict (email, plan_type, subscription_active_until, account_id) or None
          - current_model: str or None
          - thread_count: int
          - total_tokens_used: int
          - warning: str or None
    """
    home = os.path.expanduser(
        codex_home or os.environ.get("AGYKIT_DASH_CODEX_HOME") or _CODEX_HOME
    )
    auth = os.path.expanduser(auth_path or os.path.join(home, "auth.json"))
    state = os.path.expanduser(
        state_path
        or os.environ.get("AGYKIT_DASH_CODEX_STATE")
        or os.path.join(home, "state_5.sqlite")
    )

    account = None
    current_model = None
    warnings = []

    if os.path.isfile(auth):
        try:
            with open(auth) as f:
                data = json.load(f)
            token = data.get("tokens", {}).get("access_token", "")
            if token:
                payload = _decode_jwt_payload(token)
                if payload:
                    auth_data = payload.get("https://api.openai.com/auth", {})
                    profile = payload.get("https://api.openai.com/profile", {})
                    account = {
                        "email": profile.get("email", ""),
                        "plan_type": auth_data.get("chatgpt_plan_type", ""),
                        "account_id": auth_data.get("chatgpt_account_id", ""),
                        "user_id": auth_data.get("chatgpt_user_id", ""),
                        "subscription_active_until": auth_data.get(
                            "chatgpt_subscription_active_until", ""
                        ),
                    }
        except Exception as e:
            warnings.append(f"Cannot read Codex auth: {e}")

    if os.path.isfile(state):
        try:
            con = sqlite3.connect(state)
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT model FROM threads WHERE archived = 0 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                current_model = row["model"]
            thread_count_row = con.execute(
                "SELECT COUNT(*) AS c FROM threads WHERE archived = 0"
            ).fetchone()
            thread_count = thread_count_row["c"] if thread_count_row else 0
            tokens_row = con.execute(
                "SELECT SUM(tokens_used) AS t FROM threads WHERE archived = 0"
            ).fetchone()
            total_tokens = tokens_row["t"] if tokens_row and tokens_row["t"] else 0
            con.close()
        except Exception as e:
            warnings.append(f"Cannot read Codex state: {e}")
            thread_count = 0
            total_tokens = 0
    else:
        thread_count = 0
        total_tokens = 0

    available = account is not None or thread_count > 0

    sessions_dir = os.path.join(home, "sessions")
    token_usage_5h = _read_5h_token_usage(sessions_dir)

    # Live quota from Codex app-server (primary = 5h window, secondary = weekly)
    rate_limits = _fetch_codex_rate_limits()
    quota = None
    if rate_limits:
        primary = rate_limits.get("primary") or {}
        secondary = rate_limits.get("secondary") or {}
        quota = {
            "five_hour": {
                "used_pct": primary.get("usedPercent"),
                "remaining_pct": (100 - primary["usedPercent"])
                if primary.get("usedPercent") is not None
                else None,
                "resets_at": primary.get("resetsAt"),
                "window_mins": primary.get("windowDurationMins"),
            },
            "weekly": {
                "used_pct": secondary.get("usedPercent"),
                "remaining_pct": (100 - secondary["usedPercent"])
                if secondary.get("usedPercent") is not None
                else None,
                "resets_at": secondary.get("resetsAt"),
                "window_mins": secondary.get("windowDurationMins"),
            },
            "plan_type": rate_limits.get("planType"),
            "limit_id": rate_limits.get("limitId"),
            "credits": rate_limits.get("credits"),
        }

    return {
        "available": available,
        "account": account,
        "current_model": current_model,
        "thread_count": thread_count,
        "total_tokens_used": total_tokens,
        "token_usage_5h": token_usage_5h,
        "quota": quota,
        "warning": " | ".join(warnings) if warnings else None,
    }
