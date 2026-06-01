import os
import json
import urllib.request
import urllib.error

_JOB_SLACK_WEBHOOK = os.environ.get("AGYKIT_JOB_SLACK_WEBHOOK", "")
_JOB_TELEGRAM_TOKEN = os.environ.get("AGYKIT_JOB_TELEGRAM_TOKEN", "")
_JOB_TELEGRAM_CHAT_ID = os.environ.get("AGYKIT_JOB_TELEGRAM_CHAT_ID", "")
_JOB_NTFY_TOPIC = os.environ.get("AGYKIT_JOB_NTFY_TOPIC", "")


def _post_json(url: str, payload: dict) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _notify_slack(webhook: str, summary: str) -> bool:
    return _post_json(webhook, {"text": summary})


def _notify_telegram(token: str, chat_id: str, summary: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return _post_json(url, {"chat_id": chat_id, "text": summary, "parse_mode": "Markdown"})


def _notify_ntfy(topic: str, summary: str) -> bool:
    url = f"https://ntfy.sh/{topic}"
    try:
        data = summary.encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Title", "agykit Job")
        req.add_header("Tags", "hammer_and_wrench")
        urllib.request.urlopen(req, timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False


def notify(job_id: str, status: str, summary: str):
    if _JOB_SLACK_WEBHOOK:
        _notify_slack(_JOB_SLACK_WEBHOOK, summary)
    if _JOB_TELEGRAM_TOKEN and _JOB_TELEGRAM_CHAT_ID:
        _notify_telegram(_JOB_TELEGRAM_TOKEN, _JOB_TELEGRAM_CHAT_ID, summary)
    if _JOB_NTFY_TOPIC:
        _notify_ntfy(_JOB_NTFY_TOPIC, summary)
