import os
import json
import dashboard.notify as notify


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def read(self):
        return b"ok"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeUrlOpener:
    def __init__(self):
        self.last_url = None
        self.last_data = None
        self.last_headers = None
        self.fail = False

    def open(self, req, timeout=None):
        if self.fail:
            raise OSError("mock failure")
        self.last_url = req.full_url
        self.last_data = req.data
        self.last_headers = dict(req.headers)
        return _FakeResponse()


def test_notify_skips_when_no_channels(monkeypatch):
    monkeypatch.setattr(notify, "_JOB_SLACK_WEBHOOK", "")
    monkeypatch.setattr(notify, "_JOB_TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify, "_JOB_TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(notify, "_JOB_NTFY_TOPIC", "")
    # Should not raise
    notify.notify("job-1", "succeeded", "test")


def test_notify_slack_sends(monkeypatch):
    opener = _FakeUrlOpener()
    monkeypatch.setattr("urllib.request.urlopen", opener.open)
    monkeypatch.setattr(notify, "_JOB_SLACK_WEBHOOK", "https://hooks.slack.com/xxx")
    monkeypatch.setattr(notify, "_JOB_TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify, "_JOB_NTFY_TOPIC", "")

    notify.notify("job-1", "succeeded", "test message")
    assert opener.last_url == "https://hooks.slack.com/xxx"
    body = json.loads(opener.last_data)
    assert "text" in body


def test_notify_ntfy_sends(monkeypatch):
    opener = _FakeUrlOpener()
    monkeypatch.setattr("urllib.request.urlopen", opener.open)
    monkeypatch.setattr(notify, "_JOB_SLACK_WEBHOOK", "")
    monkeypatch.setattr(notify, "_JOB_TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify, "_JOB_NTFY_TOPIC", "agykit-test")

    notify.notify("job-1", "failed", "something broke")
    assert "ntfy.sh/agykit-test" in opener.last_url
    assert b"something broke" in opener.last_data


def test_notify_handles_failure_gracefully(monkeypatch):
    opener = _FakeUrlOpener()
    opener.fail = True
    monkeypatch.setattr("urllib.request.urlopen", opener.open)
    monkeypatch.setattr(notify, "_JOB_SLACK_WEBHOOK", "https://hooks.slack.com/xxx")
    monkeypatch.setattr(notify, "_JOB_TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify, "_JOB_NTFY_TOPIC", "")

    # Should not raise
    notify.notify("job-1", "succeeded", "test")
