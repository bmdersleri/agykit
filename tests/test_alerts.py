import json
import time

from dashboard import alerts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quota(email="user@example.com", model_id="gemini-3.5-pro", frac=0.05):
    return {
        "accounts": [
            {
                "email": email,
                "models": [
                    {
                        "model_id": model_id,
                        "display_name": "Gemini 3.5 Pro",
                        "remaining_fraction": frac,
                    }
                ],
                "error": None,
            }
        ],
        "warning": None,
    }


# ---------------------------------------------------------------------------
# test_threshold_detection
# ---------------------------------------------------------------------------


def test_threshold_detection(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    state = str(tmp_path / "state.json")
    result = alerts.check_quota_alerts(
        15, state_path=state, channels=["log"], ops_log_path=str(tmp_path / "ops.log")
    )
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["email"] == "user@example.com"
    assert result["alerts"][0]["model_id"] == "gemini-3.5-pro"
    assert result["warning"] is None


# ---------------------------------------------------------------------------
# test_above_threshold_no_alert
# ---------------------------------------------------------------------------


def test_above_threshold_no_alert(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.80))
    state = str(tmp_path / "state.json")
    result = alerts.check_quota_alerts(15, state_path=state, channels=[])
    assert result["alerts"] == []
    assert result["skipped_cooldown"] == []


# ---------------------------------------------------------------------------
# test_cooldown_dedup
# ---------------------------------------------------------------------------


def test_cooldown_dedup(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    state = str(tmp_path / "state.json")
    ops = str(tmp_path / "ops.log")

    first = alerts.check_quota_alerts(
        15, state_path=state, channels=["log"], ops_log_path=ops
    )
    assert len(first["alerts"]) == 1

    second = alerts.check_quota_alerts(
        15, state_path=state, channels=["log"], ops_log_path=ops
    )
    assert second["alerts"] == []
    assert len(second["skipped_cooldown"]) == 1


# ---------------------------------------------------------------------------
# test_cooldown_expired
# ---------------------------------------------------------------------------


def test_cooldown_expired(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    state = str(tmp_path / "state.json")
    ops = str(tmp_path / "ops.log")

    # Write state with old timestamp (2 hours ago)
    old_ts = time.time() - 7200
    json.dump({"user@example.com:gemini-3.5-pro": old_ts}, open(state, "w"))

    result = alerts.check_quota_alerts(
        15, state_path=state, channels=["log"], ops_log_path=ops
    )
    assert len(result["alerts"]) == 1


# ---------------------------------------------------------------------------
# test_desktop_skip_when_absent
# ---------------------------------------------------------------------------


def test_desktop_skip_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    monkeypatch.setattr(alerts.shutil, "which", lambda _: None)
    state = str(tmp_path / "state.json")
    ops = str(tmp_path / "ops.log")

    result = alerts.check_quota_alerts(
        15, state_path=state, channels=["desktop"], ops_log_path=ops
    )
    # desktop channel: which returns None → _channel_desktop returns False → not in fired
    assert "desktop" not in result["fired"]


# ---------------------------------------------------------------------------
# test_telegram_skip_when_unconfigured
# ---------------------------------------------------------------------------


def test_telegram_skip_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    monkeypatch.delenv("AGYKIT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AGYKIT_TG_CHAT_ID", raising=False)
    state = str(tmp_path / "state.json")

    result = alerts.check_quota_alerts(15, state_path=state, channels=["telegram"])
    assert "telegram" not in result["fired"]


# ---------------------------------------------------------------------------
# test_telegram_post
# ---------------------------------------------------------------------------


def test_telegram_post(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    monkeypatch.setenv("AGYKIT_TG_BOT_TOKEN", "testtoken")
    monkeypatch.setenv("AGYKIT_TG_CHAT_ID", "12345")
    state = str(tmp_path / "state.json")

    posted = []

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(req, timeout=None):
        posted.append(req.full_url)
        return _FakeResp()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    result = alerts.check_quota_alerts(15, state_path=state, channels=["telegram"])
    assert len(posted) == 1
    assert "testtoken" in posted[0]
    assert "telegram" in result["fired"]


# ---------------------------------------------------------------------------
# test_log_channel_writes
# ---------------------------------------------------------------------------


def test_log_channel_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts.collectors, "agy_model_quota", lambda: _quota(frac=0.05))
    state = str(tmp_path / "state.json")
    ops = str(tmp_path / "ops.log")

    result = alerts.check_quota_alerts(
        15, state_path=state, channels=["log"], ops_log_path=ops
    )
    assert "log" in result["fired"]
    lines = open(ops).readlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["cmd"] == "alert"
    assert entry["status"] == "quota-alert"
    assert entry["account"] == "user@example.com"
