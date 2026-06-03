import os
import json
import time
import datetime
import subprocess
import shutil
import urllib.request

from dashboard import collectors

_STATE_DEFAULT = "~/.gemini/agykit-alert-state.json"
_OPS_LOG_DEFAULT = "~/.gemini/agykit-ops.log"
_COOLDOWN_DEFAULT = 3600


def _load_state(path: str) -> dict:
    try:
        return json.load(open(path))
    except Exception:
        return {}


def _save_state(path: str, state: dict) -> None:
    try:
        json.dump(state, open(path, "w"), ensure_ascii=False)
    except Exception:
        pass


def _channel_log(alerts: list[dict], ops_log_path: str) -> None:
    path = os.path.expanduser(ops_log_path)
    try:
        with open(path, "a", encoding="utf-8") as f:
            for a in alerts:
                entry = {
                    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "cmd": "alert",
                    "status": "quota-alert",
                    "account": a["email"],
                    "model": a["model_id"],
                    "prompt": a["message"],
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _channel_desktop(alerts: list[dict]) -> bool:
    if not shutil.which("notify-send"):
        return False
    for a in alerts:
        try:
            subprocess.run(
                ["notify-send", "Agykit Kota Uyarısı", a["message"]],
                timeout=5,
            )
        except Exception:
            pass
    return True


def _channel_telegram(alerts: list[dict]) -> bool:
    token = os.environ.get("AGYKIT_TG_BOT_TOKEN")
    chat_id = os.environ.get("AGYKIT_TG_CHAT_ID")
    if not token or not chat_id:
        return False
    text = "\n".join(a["message"] for a in alerts)
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
    return True


def check_quota_alerts(
    threshold_pct: int | None = None,
    *,
    state_path: str | None = None,
    channels: list[str] | None = None,
    ops_log_path: str | None = None,
) -> dict:
    """Check per-model quota and fire alerts for models below threshold.

    Returns {"alerts", "fired", "skipped_cooldown", "warning"}
    """
    if threshold_pct is None:
        threshold_pct = int(os.environ.get("AGYKIT_QUOTA_ALERT_PCT", "15"))
    cooldown = int(os.environ.get("AGYKIT_ALERT_COOLDOWN", str(_COOLDOWN_DEFAULT)))
    resolved_state = os.path.expanduser(state_path or _STATE_DEFAULT)

    quota = collectors.agy_model_quota()
    if quota.get("warning") and not quota.get("accounts"):
        return {
            "alerts": [],
            "fired": [],
            "skipped_cooldown": [],
            "warning": quota["warning"],
        }

    state = _load_state(resolved_state)
    now = time.time()
    threshold_frac = threshold_pct / 100.0

    to_fire: list[dict] = []
    skipped: list[str] = []

    for account in quota.get("accounts", []):
        email = account["email"]
        for model in account.get("models", []):
            frac = model.get("remaining_fraction", 1.0)
            if frac >= threshold_frac:
                continue
            key = f"{email}:{model['model_id']}"
            last = state.get(key, 0)
            if now - last < cooldown:
                skipped.append(key)
                continue
            pct_left = round(frac * 100)
            msg = f"⚠ {email} — {model['display_name']} %{pct_left} kaldı"
            to_fire.append(
                {
                    "email": email,
                    "model_id": model["model_id"],
                    "display_name": model["display_name"],
                    "pct_remaining": pct_left,
                    "message": msg,
                }
            )
            state[key] = now

    if to_fire:
        _save_state(resolved_state, state)

    fired: list[str] = []

    # Determine active channels
    if channels is None:
        active = ["log"]
        if shutil.which("notify-send"):
            active.append("desktop")
        if os.environ.get("AGYKIT_TG_BOT_TOKEN") and os.environ.get(
            "AGYKIT_TG_CHAT_ID"
        ):
            active.append("telegram")
    else:
        active = channels

    if to_fire:
        if "log" in active:
            _channel_log(to_fire, ops_log_path or _OPS_LOG_DEFAULT)
            fired.append("log")
        if "desktop" in active:
            if _channel_desktop(to_fire):
                fired.append("desktop")
        if "telegram" in active:
            if _channel_telegram(to_fire):
                fired.append("telegram")

    return {
        "alerts": to_fire,
        "fired": fired,
        "skipped_cooldown": skipped,
        "warning": quota.get("warning"),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "check":
        result = check_quota_alerts()
        n = len(result["alerts"])
        sk = len(result["skipped_cooldown"])
        print(f"quota-alerts: {n} fired, {sk} cooldown-skipped")
        sys.exit(0)
