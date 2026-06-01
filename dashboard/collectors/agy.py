import os
import json
import glob
import datetime
import re
import time as _time

from ._common import _apply_range

_LOG_DIR_DEFAULT = "~/.gemini/antigravity-cli/log"
_LOG_FILE_RE = re.compile(r"cli-(\d{8})_(\d{6})\.log$")
_LINE_RE = re.compile(r"^[IWEF](\d{2})(\d{2}) (\d{2}:\d{2}:\d{2})\.\d+")
_RESET_RE = re.compile(r"Resets in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
_EMAIL_RE = re.compile(r"email=([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})")
_QUOTA_WINDOW_SECONDS = 4 * 3600

_BRAIN_DIR_DEFAULT = "~/.gemini/antigravity-cli/brain"
_STATUSLINE_JSON = "~/.gemini/antigravity-cli/statusline.json"

_MODEL_DISPLAY = {
    "gemini-2.5-flash":      "Gemini 2.5 Flash",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    "gemini-2.5-pro":        "Gemini 2.5 Pro",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gemini-3.5-flash":      "Gemini 3.5 Flash",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "gemini-3.5-pro":        "Gemini 3.5 Pro",
    "gemini-3.1-pro":        "Gemini 3.1 Pro",
    "gemini-3.1-flash":      "Gemini 3.1 Flash",
}
_QUOTA_URL  = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
_TOKEN_URL  = "https://oauth2.googleapis.com/token"
_CLIENT_ID  = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
_CLIENT_SEC = "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"  # from agy binary

_QUOTA_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")
_QUOTA_CACHE_TTL = 300  # 5 minutes
_PLANS_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/account-plans.json")


def agy_series(range_key: str = "all", *, brain_dir: str | None = None) -> dict:
    if brain_dir is None:
        brain_dir = os.path.expanduser(_BRAIN_DIR_DEFAULT)

    if not os.path.isdir(brain_dir):
        return {
            "labels": [],
            "sessions": [],
            "tool_calls": [],
            "model_mix": {},
            "warning": f"Directory not found: {brain_dir}",
            "skipped": 0,
        }

    pattern = os.path.join(
        brain_dir, "*", ".system_generated", "logs", "transcript_full.jsonl"
    )
    files = glob.glob(pattern)

    if not files:
        return {
            "labels": [],
            "sessions": [],
            "tool_calls": [],
            "model_mix": {},
            "warning": f"No transcript files found in: {brain_dir}",
            "skipped": 0,
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
            date = max_created_at[:10]
            session_newest[filepath] = date

    sessions_by_date = {}
    for filepath, date in session_newest.items():
        sessions_by_date[date] = sessions_by_date.get(date, 0) + 1

    sorted_dates = sorted(list(all_dates))
    filtered_dates = _apply_range(sorted_dates, range_key)
    sorted_models = sorted(list(all_models))

    sessions_list = []
    tool_calls_list = []
    model_mix: dict = {model: [] for model in sorted_models}

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
        "skipped": skipped,
    }


def agy_quota_status(*, log_dir: str | None = None) -> dict:
    """Return per-account quota status parsed from agy CLI logs."""
    base = os.path.expanduser(log_dir or _LOG_DIR_DEFAULT)
    if not os.path.isdir(base):
        return {
            "accounts": [],
            "quota_window_seconds": _QUOTA_WINDOW_SECONDS,
            "warning": f"Log dir not found: {base}",
        }

    logs = sorted(glob.glob(os.path.join(base, "cli-*.log")))
    if not logs:
        return {
            "accounts": [],
            "quota_window_seconds": _QUOTA_WINDOW_SECONDS,
            "warning": "No agy CLI logs found",
        }

    best: dict[str, dict] = {}
    sessions: dict[str, int] = {}
    exhaustions: dict[str, int] = {}
    max_reset_dur = _QUOTA_WINDOW_SECONDS

    for path in logs:
        m = _LOG_FILE_RE.search(os.path.basename(path))
        if not m:
            continue
        year = int(m.group(1)[:4])

        email = None
        session_counted = False
        try:
            for line in open(path, errors="replace"):
                em = _EMAIL_RE.search(line)
                if em:
                    email = em.group(1)
                    if not session_counted:
                        sessions[email] = sessions.get(email, 0) + 1
                        session_counted = True

                if "429" not in line and "quota" not in line.lower():
                    continue

                lm = _LINE_RE.match(line)
                if not lm:
                    continue
                mon, day, hms = int(lm.group(1)), int(lm.group(2)), lm.group(3)
                h, mi, s = map(int, hms.split(":"))
                try:
                    logged_at = datetime.datetime(year, mon, day, h, mi, s,
                                                  tzinfo=datetime.timezone.utc)
                except ValueError:
                    continue

                rm = _RESET_RE.search(line)
                reset_dur_s = 0
                if rm:
                    reset_dur_s = (int(rm.group(1) or 0) * 3600
                                   + int(rm.group(2) or 0) * 60
                                   + int(rm.group(3) or 0))
                    if reset_dur_s > max_reset_dur:
                        max_reset_dur = reset_dur_s

                reset_abs = logged_at + datetime.timedelta(seconds=reset_dur_s) if reset_dur_s else None

                if email:
                    exhaustions[email] = exhaustions.get(email, 0) + 1
                    if email not in best or logged_at > best[email]["logged_at"]:
                        best[email] = {
                            "logged_at": logged_at,
                            "reset_abs": reset_abs,
                            "reset_dur_s": reset_dur_s,
                        }
        except Exception:
            continue

    now = datetime.datetime.now(datetime.timezone.utc)
    accounts = []
    for email, info in sorted(best.items()):
        reset_abs = info["reset_abs"]
        resets_in = max(0, int((reset_abs - now).total_seconds())) if reset_abs else 0
        elapsed = int((now - info["logged_at"]).total_seconds())
        status = "exhausted" if resets_in > 0 else "available"
        accounts.append({
            "email": email,
            "status": status,
            "last_exhausted_at": info["logged_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resets_at": reset_abs.strftime("%Y-%m-%dT%H:%M:%SZ") if reset_abs else None,
            "resets_in_seconds": resets_in,
            "elapsed_seconds": elapsed,
            "session_count": sessions.get(email, 0),
            "exhaustion_count": exhaustions.get(email, 0),
        })

    return {
        "accounts": accounts,
        "quota_window_seconds": max_reset_dur,
        "warning": None,
    }


def agy_statusline_snapshot(*, path: str | None = None) -> dict:
    """Read the last-captured agy statusline JSON snapshot."""
    p = os.path.expanduser(path or _STATUSLINE_JSON)
    if not os.path.isfile(p):
        return {
            "available": False,
            "warning": "No statusline snapshot yet. Run agy to populate.",
        }
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p))
        age_s = (datetime.datetime.now() - mtime).total_seconds()
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        cw = raw.get("context_window") or {}
        model = raw.get("model") or {}
        vcs = raw.get("vcs") or {}
        artifacts = raw.get("artifacts", raw.get("artifact_count", 0))
        subagents = raw.get("subagents", 0)
        bg_tasks = raw.get("background_tasks", raw.get("task_count", 0))
        return {
            "available": True,
            "captured_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
            "age_seconds": int(age_s),
            "agent_state": raw.get("agent_state", "idle"),
            "context_pct": cw.get("used_percentage", 0),
            "context_input_tokens": cw.get("total_input_tokens", 0),
            "context_output_tokens": cw.get("total_output_tokens", 0),
            "model": model.get("display_name") or model.get("id") or raw.get("model", ""),
            "plan_tier": raw.get("plan_tier", ""),
            "email": raw.get("email", ""),
            "vcs_branch": vcs.get("branch", ""),
            "vcs_dirty": vcs.get("dirty", False),
            "artifact_count": artifacts,
            "subagent_count": subagents,
            "bg_task_count": bg_tasks,
        }
    except Exception as e:
        return {"available": False, "warning": str(e)}


def agy_last_session(*, brain_dir: str | None = None) -> dict:
    """Summarise the most-recent agy brain session from its transcript."""
    base = os.path.expanduser(brain_dir or _BRAIN_DIR_DEFAULT)
    pattern = os.path.join(
        base, "*", ".system_generated", "logs", "transcript_full.jsonl"
    )
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not files:
        return {"available": False, "warning": "No brain transcripts found"}
    f = files[-1]
    session_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(f))))
    records, skipped = [], 0
    try:
        for line in open(f, errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                skipped += 1
    except Exception as e:
        return {"available": False, "warning": str(e)}
    if not records:
        return {"available": False, "warning": "Empty transcript"}

    times = [r["created_at"] for r in records if r.get("created_at")]
    started = min(times) if times else None
    ended = max(times) if times else None
    dur = 0
    if started and ended:
        try:
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            dur = int(
                (
                    datetime.datetime.strptime(ended, fmt)
                    - datetime.datetime.strptime(started, fmt)
                ).total_seconds()
            )
        except Exception:
            pass
    models = [r["model"] for r in records if r.get("model")]
    model = max(set(models), key=models.count) if models else None
    tool_calls = sum(1 for r in records if r.get("type") == "tool_call")
    type_counts: dict[str, int] = {}
    for r in records:
        t = r.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "available": True,
        "session_id": session_id,
        "started_at": started,
        "ended_at": ended,
        "duration_seconds": dur,
        "record_count": len(records),
        "tool_call_count": tool_calls,
        "model": model,
        "record_types": type_counts,
        "warning": f"Skipped {skipped} malformed lines" if skipped else None,
    }


def _google_userinfo(access_token: str) -> dict:
    """Fetch Google userinfo (email, name, picture) for a given access token."""
    import urllib.request
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def agy_active_account() -> dict:
    """Return active agy account info (email, name, picture) via Google userinfo."""
    try:
        import keyring
        v = keyring.get_password("gemini", "antigravity")
        if not v:
            return {"email": None, "picture": None, "warning": "No keyring entry"}
        token = json.loads(v)["token"]["access_token"]
        info = _google_userinfo(token)
        return {
            "email":   info.get("email", ""),
            "name":    info.get("name", ""),
            "picture": info.get("picture"),
            "warning": None,
        }
    except Exception as e:
        return {"email": None, "picture": None, "warning": str(e)[:80]}


def _refresh_access_token(refresh_token: str) -> str:
    import urllib.request
    import urllib.parse
    body = urllib.parse.urlencode({
        "client_id":     _CLIENT_ID,
        "client_secret": _CLIENT_SEC,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["access_token"]


def agy_model_quota() -> dict:
    """Fetch per-model quota for all saved agy accounts."""
    import urllib.request
    accounts_dir = os.path.expanduser("~/.gemini/accounts")
    if not os.path.isdir(accounts_dir):
        return {"accounts": [], "warning": "No accounts dir found"}

    acct_files = sorted(glob.glob(os.path.join(accounts_dir, "*.json")))
    if not acct_files:
        return {"accounts": [], "warning": "No saved accounts found"}

    now = datetime.datetime.now(datetime.timezone.utc)
    accounts = []
    warnings = []

    for f in acct_files:
        email = os.path.basename(f).replace(".json", "")
        try:
            rt = json.load(open(f))["token"]["refresh_token"]
            at = _refresh_access_token(rt)
            req = urllib.request.Request(_QUOTA_URL,
                headers={"Authorization": f"Bearer {at}",
                         "Content-Type": "application/json"},
                data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
            models = []
            for b in d.get("buckets", []):
                mid   = b.get("modelId", "")
                frac  = float(b.get("remainingFraction", 1))
                rtime = b.get("resetTime")
                resets_in = 0
                resets_at_str = None
                if rtime:
                    try:
                        rdt = datetime.datetime.fromisoformat(rtime)
                        resets_at_str = rdt.astimezone().strftime("%Y-%m-%d %H:%M")
                        resets_in = max(0, int((rdt - now).total_seconds()))
                    except Exception:
                        pass
                models.append({
                    "model_id":           mid,
                    "display_name":       _MODEL_DISPLAY.get(mid, mid),
                    "remaining_fraction": round(frac, 4),
                    "used_pct":           round((1 - frac) * 100, 1),
                    "pct_remaining":      round(frac * 100, 1),
                    "resets_at":          resets_at_str,
                    "resets_in_seconds":  resets_in,
                    "token_type":         b.get("tokenType", ""),
                })
            all_full = all(m["remaining_fraction"] >= 1.0 for m in models)
            tier_note = "standard-tier (unlimited)" if all_full and models else None
            accounts.append({"email": email, "models": models, "error": None, "tier_note": tier_note})
        except Exception as e:
            accounts.append({"email": email, "models": [], "error": str(e)[:80]})
            warnings.append(f"{email}: {e}")

    return {"accounts": accounts, "warning": ("; ".join(warnings) if warnings else None)}


def agy_model_quota_tmux(*, session: str = "agykit-quota-snap") -> dict:
    """Capture model quota from agy /usage screen via tmux pane capture."""
    import subprocess
    import time

    def run(*cmd):
        return subprocess.run(list(cmd), capture_output=True, text=True)

    run("tmux", "kill-session", "-t", session)
    time.sleep(0.3)

    r = run("tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "60", "agy")
    if r.returncode != 0:
        return {"models": [], "warning": f"tmux failed: {r.stderr[:60]}",
                "account": None, "plan": None, "captured_at": None}

    deadline = time.time() + 40
    ready = False
    while time.time() < deadline:
        cap = run("tmux", "capture-pane", "-t", session, "-p")
        pane = cap.stdout
        if "trust" in pane.lower() and ("Yes" in pane or "enter" in pane.lower()):
            run("tmux", "send-keys", "-t", session, "", "Enter")
            time.sleep(1)
            continue
        if "● READY" in pane or ("READY" in pane and "INITIALIZING" not in pane):
            ready = True
            break
        time.sleep(1)

    if not ready:
        run("tmux", "kill-session", "-t", session)
        return {"models": [], "warning": "agy did not reach READY state",
                "account": None, "plan": None, "captured_at": None}

    time.sleep(1)

    statusline = run("tmux", "capture-pane", "-t", session, "-p").stdout
    account, plan = None, None
    m = re.search(r'([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', statusline)
    if m:
        account = m.group(1)
    m = re.search(r'Google AI Pro|standard-tier|Pro Plus|Free', statusline)
    if m:
        plan = m.group(0)

    run("tmux", "send-keys", "-t", session, "/usage", "Enter")

    deadline2 = time.time() + 20
    while time.time() < deadline2:
        cap = run("tmux", "capture-pane", "-t", session, "-p", "-S", "-", "-E", "-")
        if any(k in cap.stdout for k in ["Model Quota", "Gemini 3.5", "Refreshes in", "Quota available"]):
            break
        time.sleep(1)

    time.sleep(2)

    cap = run("tmux", "capture-pane", "-t", session, "-p", "-S", "-", "-E", "-")
    raw = cap.stdout

    run("tmux", "kill-session", "-t", session)

    MODEL_RE = re.compile(r'^(Gemini|Claude|GPT|Llama|Mistral|Qwen|Deepseek|Grok)')
    raw_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    models = []
    for i, line in enumerate(raw_lines):
        if not MODEL_RE.match(line):
            continue
        model_name = line
        pct = None
        bar_blocks = 0
        status = "available"
        refreshes_in = None
        for ln in raw_lines[i + 1 : i + 4]:
            if MODEL_RE.match(ln):
                break
            m2 = re.search(r'(\d+)%', ln)
            if m2:
                pct = int(m2.group(1))
                bar_blocks = ln.count('█')
            if 'Quota available' in ln or 'quota available' in ln.lower():
                status = "available"
            m3 = re.search(r'Refreshes? in (.+)', ln)
            if m3:
                refreshes_in = m3.group(1).strip()
                status = "limited"
        models.append({
            "display_name":  model_name,
            "pct_shown":     pct,
            "pct_remaining": pct,
            "status":        status,
            "refreshes_in":  refreshes_in,
            "bar_blocks":    bar_blocks,
        })

    captured_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    warning = None if models else "No model quota data found in screen output"
    return {
        "models":      models,
        "account":     account,
        "plan":        plan,
        "captured_at": captured_at,
        "warning":     warning,
    }


def _load_plans_cache() -> dict:
    try:
        return json.load(open(_PLANS_CACHE))
    except Exception:
        return {}


def _save_plan(email: str, plan: str) -> None:
    if not email or not plan:
        return
    try:
        plans = _load_plans_cache()
        plans[email] = plan
        json.dump(plans, open(_PLANS_CACHE, "w"), ensure_ascii=False, indent=2)
    except Exception:
        pass


def agy_model_quota_cached(*, force: bool = False) -> dict:
    """Return model quota from cache if fresh, else run tmux capture and cache."""
    if not force and os.path.isfile(_QUOTA_CACHE):
        try:
            cached = json.load(open(_QUOTA_CACHE))
            age = _time.time() - cached.get("_ts", 0)
            if age < _QUOTA_CACHE_TTL:
                cached["_cache_age_seconds"] = int(age)
                cached["_from_cache"] = True
                return cached
        except Exception:
            pass

    data = agy_model_quota_tmux()

    if data.get("models"):
        try:
            data["_ts"] = _time.time()
            json.dump(data, open(_QUOTA_CACHE, "w"), ensure_ascii=False, indent=2)
        except Exception:
            pass
        if data.get("account") and data.get("plan"):
            _save_plan(data["account"], data["plan"])
    data["_from_cache"] = False
    return data


def _fetch_quota_reset_times() -> dict | None:
    """Get reset time from retrieveUserQuota (fast, no tmux needed)."""
    import urllib.request
    try:
        import keyring
        v = keyring.get_password("gemini", "antigravity")
        token = json.loads(v)["token"]["access_token"]
        req = urllib.request.Request(
            "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        buckets = d.get("buckets", [])
        if not buckets:
            return None
        rt = buckets[0].get("resetTime")
        if not rt:
            return None
        rdt = datetime.datetime.fromisoformat(rt)
        now = datetime.datetime.now(datetime.timezone.utc)
        secs = max(0, int((rdt - now).total_seconds()))
        h, mi = secs // 3600, (secs % 3600) // 60
        label = f"{h}sa {mi}dk" if h else f"{mi}dk"
        return {
            "reset_at":      rdt.astimezone().strftime("%H:%M"),
            "reset_in_secs": secs,
            "label":         label,
        }
    except Exception:
        return None


def agy_refresh_all_accounts(*, agykit_path: str | None = None) -> dict:
    """Switch to each saved agy account and run a lightweight agy --print to refresh log data."""
    import subprocess
    import shutil

    agykit = agykit_path or shutil.which("agykit")
    if not agykit:
        return {"results": [], "warning": "agykit not found in PATH"}

    accounts_dir = os.path.expanduser("~/.gemini/accounts")
    if not os.path.isdir(accounts_dir):
        return {"results": [], "warning": "No accounts dir found"}

    emails = sorted(
        os.path.basename(f).replace(".json", "")
        for f in glob.glob(os.path.join(accounts_dir, "*.json"))
    )
    if not emails:
        return {"results": [], "warning": "No saved accounts found"}

    results = []
    for email in emails:
        try:
            sw = subprocess.run(
                [agykit, "switch", email], capture_output=True, text=True, timeout=15
            )
            if sw.returncode != 0:
                results.append(
                    {"email": email, "ok": False, "error": sw.stderr.strip()[:80]}
                )
                continue
            run = subprocess.run(
                [agykit, "run", "echo ok"], capture_output=True, text=True, timeout=60
            )
            ok = run.returncode == 0
            results.append({
                "email": email,
                "ok": ok,
                "error": run.stderr.strip()[:80] if not ok else None,
            })
        except subprocess.TimeoutExpired:
            results.append({"email": email, "ok": False, "error": "timeout"})
        except Exception as e:
            results.append({"email": email, "ok": False, "error": str(e)[:80]})

    return {"results": results, "warning": None}
