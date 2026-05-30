import os
import json
import glob
import datetime
import re

def _apply_range(labels: list[str], range_key: str) -> list[str]:
    if not labels:
        return []
    if range_key == "all":
        return labels
    
    try:
        max_date = datetime.date.fromisoformat(max(labels))
    except ValueError:
        return labels

    if range_key == "7d":
        limit = max_date - datetime.timedelta(days=7)
    elif range_key == "30d":
        limit = max_date - datetime.timedelta(days=30)
    else:
        return labels
        
    return [d for d in labels if datetime.date.fromisoformat(d) > limit]

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
            "warning": f"File not found: {stats_path}"
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
            "warning": f"Error reading file: {e}"
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
    
    activity_map = {item["date"]: item for item in data.get("dailyActivity", []) if "date" in item}
    tokens_map = {item["date"]: item for item in data.get("dailyModelTokens", []) if "date" in item}
    
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
        "warning": None
    }

def agy_series(range_key: str = "all", *, brain_dir: str | None = None) -> dict:
    if brain_dir is None:
        brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain")
        
    if not os.path.isdir(brain_dir):
        return {
            "labels": [],
            "sessions": [],
            "tool_calls": [],
            "model_mix": {},
            "warning": f"Directory not found: {brain_dir}",
            "skipped": 0
        }
        
    pattern = os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript_full.jsonl")
    files = glob.glob(pattern)
    
    if not files:
        return {
            "labels": [],
            "sessions": [],
            "tool_calls": [],
            "model_mix": {},
            "warning": f"No transcript files found in: {brain_dir}",
            "skipped": 0
        }
        
    session_newest = {}
    tool_calls_by_date = {}
    model_mix_by_date = {}
    all_dates = set()
    all_models = set()
    skipped = 0
    
    for filepath in files:
        max_created_at = None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
            
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            try:
                record = json.loads(line_stripped)
            except Exception:
                skipped += 1
                continue
                
            created_at = record.get("created_at")
            if not created_at or len(created_at) < 10:
                continue
                
            date = created_at[:10]
            all_dates.add(date)
            
            if max_created_at is None or created_at > max_created_at:
                max_created_at = created_at
                
            tcalls = record.get("tool_calls")
            tcall_count = len(tcalls) if isinstance(tcalls, list) else 0
            tool_calls_by_date[date] = tool_calls_by_date.get(date, 0) + tcall_count
            
            model = record.get("model")
            if model:
                all_models.add(model)
                if date not in model_mix_by_date:
                    model_mix_by_date[date] = {}
                model_mix_by_date[date][model] = model_mix_by_date[date].get(model, 0) + 1
                
        if max_created_at:
            session_newest[filepath] = max_created_at
            
    if not all_dates:
        return {
            "labels": [],
            "sessions": [],
            "tool_calls": [],
            "model_mix": {},
            "warning": "No valid activity records found" if skipped == 0 else f"No valid activity records found. Skipped {skipped} malformed line(s)",
            "skipped": skipped
        }
        
    sorted_dates = sorted(list(all_dates))
    filtered_dates = _apply_range(sorted_dates, range_key)
    
    sessions_by_date = {}
    for filepath, newest_created_at in session_newest.items():
        date = newest_created_at[:10]
        sessions_by_date[date] = sessions_by_date.get(date, 0) + 1
        
    sessions_list = []
    tool_calls_list = []
    sorted_models = sorted(list(all_models))
    model_mix = {model: [] for model in sorted_models}
    
    for date in filtered_dates:
        sessions_list.append(sessions_by_date.get(date, 0))
        tool_calls_list.append(tool_calls_by_date.get(date, 0))
        for model in sorted_models:
            model_mix[model].append(model_mix_by_date.get(date, {}).get(model, 0))
            
    warning = None
    if skipped > 0:
        warning = f"Skipped {skipped} malformed line(s)"
        
    return {
        "labels": filtered_dates,
        "sessions": sessions_list,
        "tool_calls": tool_calls_list,
        "model_mix": model_mix,
        "warning": warning,
        "skipped": skipped
    }

_LOG_DIR_DEFAULT = "~/.gemini/antigravity-cli/log"
_LOG_FILE_RE = re.compile(r'cli-(\d{8})_(\d{6})\.log$')
_LINE_RE = re.compile(r'^[IWEF](\d{2})(\d{2}) (\d{2}:\d{2}:\d{2})\.\d+')
_RESET_RE = re.compile(r'Resets in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?')
_EMAIL_RE = re.compile(r'email=([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})')


def agy_quota_status(*, log_dir: str | None = None) -> dict:
    """Return per-account quota status parsed from agy CLI logs.

    Returns:
        {"accounts": [{"email", "status", "last_exhausted_at", "resets_at",
                       "resets_in_seconds"}], "warning": str|None}
    status: "available" | "exhausted"
    resets_in_seconds: seconds until reset (0 if already reset / available)
    """
    base = os.path.expanduser(log_dir or _LOG_DIR_DEFAULT)
    if not os.path.isdir(base):
        return {"accounts": [], "warning": f"Log dir not found: {base}"}

    logs = sorted(glob.glob(os.path.join(base, "cli-*.log")))
    if not logs:
        return {"accounts": [], "warning": "No agy CLI logs found"}

    # email → latest 429 event: {logged_at, reset_abs}
    best: dict[str, dict] = {}

    for path in logs:
        m = _LOG_FILE_RE.search(os.path.basename(path))
        if not m:
            continue
        year = int(m.group(1)[:4])

        email = None
        try:
            for line in open(path, errors="replace"):
                em = _EMAIL_RE.search(line)
                if em:
                    email = em.group(1)

                lm = _LINE_RE.match(line)
                if not lm or not email:
                    continue
                month, day = int(lm.group(1)), int(lm.group(2))
                h, mi, s = map(int, lm.group(3).split(":"))
                try:
                    log_ts = datetime.datetime(year, month, day, h, mi, s)
                except ValueError:
                    continue

                rm = _RESET_RE.search(line)
                if rm:
                    hours = int(rm.group(1) or 0)
                    mins  = int(rm.group(2) or 0)
                    secs  = int(rm.group(3) or 0)
                    delta = datetime.timedelta(hours=hours, minutes=mins, seconds=secs)
                    reset_abs = log_ts + delta
                    prev = best.get(email)
                    if prev is None or log_ts > prev["logged_at"]:
                        best[email] = {"logged_at": log_ts, "reset_abs": reset_abs}
        except Exception:
            continue

    now = datetime.datetime.now()
    accounts = []
    for email, v in sorted(best.items()):
        remaining = (v["reset_abs"] - now).total_seconds()
        if remaining > 0:
            status = "exhausted"
            resets_in = int(remaining)
        else:
            status = "available"
            resets_in = 0
        accounts.append({
            "email": email,
            "status": status,
            "last_exhausted_at": v["logged_at"].strftime("%Y-%m-%d %H:%M"),
            "resets_at": v["reset_abs"].strftime("%Y-%m-%d %H:%M"),
            "resets_in_seconds": resets_in,
        })

    # accounts present in ~/.gemini/accounts/ but never seen exhausted → available
    accounts_dir = os.path.expanduser("~/.gemini/accounts")
    known_emails = {a["email"] for a in accounts}
    if os.path.isdir(accounts_dir):
        for f in glob.glob(os.path.join(accounts_dir, "*.json")):
            email = os.path.basename(f).replace(".json", "")
            if email not in known_emails:
                accounts.append({
                    "email": email,
                    "status": "available",
                    "last_exhausted_at": None,
                    "resets_at": None,
                    "resets_in_seconds": 0,
                })

    return {"accounts": accounts, "warning": None}
