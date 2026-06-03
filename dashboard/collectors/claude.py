import os
import json
import datetime
from collections import deque

from ._common import _apply_range

_CLAUDE_USAGE_URL = "https://claude.ai/api/oauth/usage"
_CLAUDE_CREDS = "~/.claude/.credentials.json"

_QUOTA_LABELS = {
    "five_hour": "Oturum (5s)",
    "seven_day": "Haftalık (7g)",
    "seven_day_sonnet": "Haftalık Sonnet (7g)",
    "seven_day_opus": "Haftalık Opus (7g)",
    "seven_day_cowork": "Haftalık CoWork (7g)",
    "seven_day_omelette": "Haftalık Omelette (7g)",
    "seven_day_oauth_apps": "Haftalık OAuth Apps (7g)",
    "tangelo": "Tangelo",
    "iguana_necktie": "Iguana Necktie",
    "omelette_promotional": "Omelette Promo",
}


def _normalize_utilization_pct(value) -> float:
    """Normalize Claude usage utilization to a 0-100 percentage."""
    try:
        util = float(value or 0.0)
    except (TypeError, ValueError):
        util = 0.0
    if util <= 1:
        util *= 100
    return max(0.0, min(100.0, util))


def claude_series(range_key: str = "all", *, stats_path: str | None = None) -> dict:
    if stats_path is None:
        stats_path = os.path.expanduser("~/.claude/stats-cache.json")

    if not os.path.isfile(stats_path):
        return {
            "labels": [],
            "tokens_total": [],
            "tokens_by_model": {},
            "messages": [],
            "sessions": [],
            "tool_calls": [],
            "warning": f"File not found: {stats_path}",
        }

    try:
        with open(stats_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {
            "labels": [],
            "tokens_total": [],
            "tokens_by_model": {},
            "messages": [],
            "sessions": [],
            "tool_calls": [],
            "warning": f"Error reading file: {e}",
        }

    dates = set()
    for item in data.get("dailyActivity", []):
        if "date" in item:
            dates.add(item["date"])
    for item in data.get("dailyModelTokens", []):
        if "date" in item:
            dates.add(item["date"])

    sorted_dates = sorted(list(dates))
    filtered_dates = _apply_range(sorted_dates, range_key)

    activity_map = {
        item["date"]: item for item in data.get("dailyActivity", []) if "date" in item
    }
    tokens_map = {
        item["date"]: item
        for item in data.get("dailyModelTokens", [])
        if "date" in item
    }

    models = set()
    for item in data.get("dailyModelTokens", []):
        for model_name in item.get("tokensByModel", {}).keys():
            models.add(model_name)
    sorted_models = sorted(list(models))

    tokens_total = []
    tokens_by_model = {model: [] for model in sorted_models}
    messages = []
    sessions = []
    tool_calls = []

    for date in filtered_dates:
        act = activity_map.get(date, {})
        messages.append(act.get("messageCount", 0))
        sessions.append(act.get("sessionCount", 0))
        tool_calls.append(act.get("toolCallCount", 0))

        tok = tokens_map.get(date, {})
        t_by_m = tok.get("tokensByModel", {})

        day_total = 0
        for model in sorted_models:
            val = t_by_m.get(model, 0)
            tokens_by_model[model].append(val)
            day_total += val
        tokens_total.append(day_total)

    return {
        "labels": filtered_dates,
        "tokens_total": tokens_total,
        "tokens_by_model": tokens_by_model,
        "messages": messages,
        "sessions": sessions,
        "tool_calls": tool_calls,
        "warning": None,
    }


_CLAUDE_OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def _refresh_claude_token(creds: dict, cp: str) -> str | None:
    """Try to refresh the Claude OAuth access token using the refresh_token.

    Writes the updated credentials back to `cp` on success.
    Returns the new access token or None on failure.
    """
    import urllib.request
    import urllib.parse
    import time

    oauth = creds.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken", "")
    if not refresh_token:
        return None

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _CLAUDE_CLIENT_ID,
        }
    ).encode()

    try:
        req = urllib.request.Request(
            _CLAUDE_OAUTH_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
    except Exception:
        return None

    new_access = resp.get("access_token", "")
    if not new_access:
        return None

    new_refresh = resp.get("refresh_token", refresh_token)
    expires_in = int(resp.get("expires_in", 3600))
    new_exp_ms = int((time.time() + expires_in) * 1000)

    oauth["accessToken"] = new_access
    oauth["refreshToken"] = new_refresh
    oauth["expiresAt"] = new_exp_ms

    try:
        with open(cp, "w") as f:
            json.dump(creds, f, indent=2)
    except Exception:
        pass

    return new_access


def _get_claude_token(cp: str) -> tuple[str, str | None]:
    """Load credentials and return (access_token, warning).

    If the stored token is expired or close to expiry, attempts a refresh.
    Falls back to the stored token if refresh fails (caller will get 401).
    """
    import time

    try:
        with open(cp) as f:
            creds = json.load(f)
        oauth = creds["claudeAiOauth"]
        token = oauth["accessToken"]
    except Exception as e:
        return "", f"Cannot read creds: {e}"

    exp_ms = oauth.get("expiresAt", 0)
    now_ms = time.time() * 1000
    # Refresh proactively if token expires within 5 minutes
    if exp_ms and now_ms >= exp_ms - 300_000:
        new_token = _refresh_claude_token(creds, cp)
        if new_token:
            return new_token, None

    return token, None


def claude_quota(*, creds_path: str | None = None) -> dict:
    """Fetch live Claude Code quota from the /api/oauth/usage endpoint.

    Requires the OAuth access token stored in ~/.claude/.credentials.json.
    Returns:
        {"quotas": [{"key", "label", "utilization", "resets_at",
                     "resets_in_seconds", "pct_remaining"}],
         "extra_usage": {...},
         "warning": str|None}
    utilization: 0–100 (100 = fully exhausted).
    pct_remaining: 100 − utilization.
    resets_in_seconds: seconds until reset window refills; 0 if null/past.
    """
    import urllib.request
    import urllib.error

    cp = os.path.expanduser(creds_path or _CLAUDE_CREDS)

    token, warn = _get_claude_token(cp)
    if not token:
        return {"quotas": [], "extra_usage": None, "warning": warn or "No token"}

    try:
        req = urllib.request.Request(
            _CLAUDE_USAGE_URL,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "claude-code"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Token rejected — try one forced refresh
            try:
                with open(cp) as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
            new_token = _refresh_claude_token(creds, cp)
            if new_token:
                try:
                    req2 = urllib.request.Request(
                        _CLAUDE_USAGE_URL,
                        headers={
                            "Authorization": f"Bearer {new_token}",
                            "User-Agent": "claude-code",
                        },
                    )
                    with urllib.request.urlopen(req2, timeout=10) as r2:
                        data = json.loads(r2.read())
                except Exception as e2:
                    return {
                        "quotas": [],
                        "extra_usage": None,
                        "warning": f"API error after refresh: {e2}",
                    }
            else:
                return {
                    "quotas": [],
                    "extra_usage": None,
                    "warning": "Token expired — run `claude` once to re-authenticate",
                }
        else:
            return {"quotas": [], "extra_usage": None, "warning": f"API error: {e}"}
    except Exception as e:
        return {"quotas": [], "extra_usage": None, "warning": f"API error: {e}"}

    now = datetime.datetime.now(datetime.timezone.utc)
    quotas = []
    for key, label in _QUOTA_LABELS.items():
        entry = data.get(key)
        if entry is None:
            continue
        util_pct = _normalize_utilization_pct(entry.get("utilization"))
        resets_raw = entry.get("resets_at")
        resets_in = 0
        resets_at_str = None
        if resets_raw:
            try:
                resets_dt = datetime.datetime.fromisoformat(resets_raw)
                resets_in = max(0, int((resets_dt - now).total_seconds()))
                resets_at_str = resets_dt.astimezone().strftime("%H:%M")
            except Exception:
                pass
        quotas.append(
            {
                "key": key,
                "label": label,
                "utilization": round(util_pct, 1),
                "pct_remaining": round(100 - util_pct, 1),
                "resets_at": resets_at_str,
                "resets_in_seconds": resets_in,
            }
        )

    return {
        "quotas": quotas,
        "extra_usage": data.get("extra_usage"),
        "warning": None,
    }


def cc_activity(
    limit: int = 20, *, history_path: str | None = None, stats_path: str | None = None
) -> dict:
    if history_path is None:
        history_path = os.environ.get("AGYKIT_DASH_HISTORY") or os.path.expanduser(
            "~/.claude/history.jsonl"
        )
    if stats_path is None:
        stats_path = os.environ.get("AGYKIT_DASH_STATS") or os.path.expanduser(
            "~/.claude/stats-cache.json"
        )

    recent_prompts: list[dict] = []
    if os.path.isfile(history_path):
        window: deque = deque(maxlen=limit)
        try:
            with open(history_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        window.append(entry)
                    except json.JSONDecodeError:
                        pass
            for entry in window:
                project_path = entry.get("project", "")
                recent_prompts.append(
                    {
                        "display": entry.get("display", ""),
                        "timestamp": entry.get("timestamp", 0),
                        "project": os.path.basename(project_path)
                        if project_path
                        else "",
                        "session_id": entry.get("sessionId", ""),
                    }
                )
            recent_prompts.sort(key=lambda x: x["timestamp"], reverse=True)
        except Exception:
            pass

    latest_stats: dict = {
        "available": False,
        "date": "",
        "messages": 0,
        "sessions": 0,
        "tool_calls": 0,
    }
    if os.path.isfile(stats_path):
        try:
            with open(stats_path, encoding="utf-8") as f:
                data = json.load(f)
            activity = data.get("dailyActivity", [])
            if activity:
                latest = max(activity, key=lambda x: x.get("date", ""))
                latest_stats = {
                    "available": True,
                    "date": latest.get("date", ""),
                    "messages": latest.get("messageCount", 0),
                    "sessions": latest.get("sessionCount", 0),
                    "tool_calls": latest.get("toolCallCount", 0),
                }
        except Exception:
            pass

    return {
        "recent_prompts": recent_prompts,
        "latest_stats": latest_stats,
        "warning": None,
    }


def activity_feed(
    limit: int = 25,
    *,
    log_path: str | None = None,
    history_path: str | None = None,
    stats_path: str | None = None,
) -> dict:
    """Merge agy ops events and CC prompts into a unified chronological feed."""
    from datetime import datetime, timezone
    from .ops import ops_log

    agy_result = ops_log(limit=limit, log_path=log_path)
    cc_result = cc_activity(
        limit=limit, history_path=history_path, stats_path=stats_path
    )

    events: list[dict] = []
    warnings: list[str] = []

    if agy_result.get("warning"):
        warnings.append(agy_result["warning"])
    for e in agy_result.get("entries", []):
        ts_epoch = 0
        try:
            ts_epoch = int(
                datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except Exception:
            pass
        events.append(
            {
                "ts_epoch": ts_epoch,
                "kind": "agy",
                "cmd": e.get("cmd", ""),
                "status": e.get("status", ""),
                "model": e.get("model", ""),
                "account": e.get("account", ""),
                "prompt": e.get("prompt", ""),
            }
        )

    if cc_result.get("warning"):
        warnings.append(cc_result["warning"])
    for p in cc_result.get("recent_prompts", []):
        raw_ts = p.get("timestamp", 0)
        ts_epoch = int(raw_ts // 1000) if raw_ts > 1_000_000_000_000 else int(raw_ts)
        events.append(
            {
                "ts_epoch": ts_epoch,
                "kind": "cc",
                "display": p.get("display", ""),
                "project": p.get("project", ""),
                "session_id": p.get("session_id", ""),
            }
        )

    events.sort(key=lambda x: x["ts_epoch"], reverse=True)
    events = events[:limit]

    return {
        "events": events,
        "latest_stats": cc_result.get("latest_stats", {"available": False}),
        "warning": " | ".join(warnings) if warnings else None,
    }
