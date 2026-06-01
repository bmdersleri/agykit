import json
import os


from dashboard import collectors

FIX = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "fixtures", "stats-cache.json"
)
FIXBRAIN = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "fixtures", "brain"
)


def test_claude_series_all():
    s = collectors.claude_series("all", stats_path=FIX)
    assert s["labels"] == ["2026-05-27", "2026-05-28", "2026-05-29"]
    assert s["tokens_total"] == [1500, 800, 2300]
    assert s["tokens_by_model"]["claude-opus-4-8"] == [1000, 800, 2000]
    assert s["tokens_by_model"]["claude-haiku-4-5-20251001"] == [500, 0, 300]
    assert s["messages"] == [100, 50, 200]
    assert s["sessions"] == [3, 2, 5]
    assert s["tool_calls"] == [40, 20, 80]
    assert s["warning"] is None


def test_claude_series_missing_file():
    s = collectors.claude_series("all", stats_path="/no/such.json")
    assert s["labels"] == []
    assert s["warning"]


def test_agy_series_buckets_and_skips():
    s = collectors.agy_series("all", brain_dir=FIXBRAIN)
    assert s["labels"] == ["2026-05-28", "2026-05-29"]
    assert s["sessions"] == [1, 1]
    assert s["tool_calls"] == [1, 2]
    assert s["skipped"] == 1
    assert s["warning"]


def test_agy_series_missing_dir():
    s = collectors.agy_series("all", brain_dir="/no/such/brain")
    assert s["labels"] == []
    assert s["warning"]


def test_apply_range_7d():
    labels = ["2026-05-20", "2026-05-27", "2026-05-28", "2026-05-29"]
    assert collectors._apply_range(labels, "7d") == [
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
    ]
    assert collectors._apply_range(labels, "all") == labels
    assert collectors._apply_range([], "7d") == []


# ---------------------------------------------------------------------------
# rtk_stats
# ---------------------------------------------------------------------------

_RTK_SAMPLE = """\
RTK Token Savings (Global Scope)
════════

Total commands:    100
Input tokens:      300K
Output tokens:     150K
Tokens saved:      150K (75.0%)
Total exec time:   10m0s (avg 100ms)
Efficiency meter: ████████████████████░░░░░ 75.0%

By Command
────────────────────
  #  Command                   Count   Saved    Avg%    Time  Impact
────────────────────
 1.  rtk read                     50    100K   80.0%     0ms  ██████████
 2.  rtk grep                     30     40K   60.0%     2ms  ████░░░░░░
 3.  rtk find                     20     10K   50.0%    10ms  ██░░░░░░░░
"""


class _FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_rtk_stats_parse(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.rtk.subprocess.run",
        lambda *a, **kw: _FakeProc(_RTK_SAMPLE),
    )
    s = collectors.rtk_stats()
    assert s["total_commands"] == 100
    assert s["tokens_saved"] == 150_000
    assert s["efficiency_pct"] == 75.0
    assert len(s["top_commands"]) == 3
    assert s["top_commands"][0]["cmd"] == "rtk read"
    assert s["top_commands"][0]["count"] == 50
    assert s["top_commands"][0]["saved"] == 100_000
    assert s["top_commands"][0]["avg_pct"] == 80.0
    assert s["warning"] is None


def test_rtk_stats_subprocess_failure(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.rtk.subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("rtk not found")),
    )
    s = collectors.rtk_stats()
    assert s["tokens_saved"] == 0
    assert s["warning"]


# ---------------------------------------------------------------------------
# cc_activity
# ---------------------------------------------------------------------------


def test_cc_activity_parse(tmp_path):
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        '{"display": "/start", "timestamp": 1000000000000, "project": "/home/user/projects/agykit", "sessionId": "abc"}\n'
        '{"display": "hello world", "timestamp": 1000000001000, "project": "/home/user/projects/myapp", "sessionId": "abc"}\n'
    )
    s = collectors.cc_activity(history_path=str(hist), stats_path="/no/such.json")
    assert len(s["recent_prompts"]) == 2
    # newest first
    assert s["recent_prompts"][0]["display"] == "hello world"
    assert s["recent_prompts"][0]["project"] == "myapp"
    assert s["recent_prompts"][1]["project"] == "agykit"
    assert s["latest_stats"]["available"] is False


def test_cc_activity_no_history(tmp_path):
    s = collectors.cc_activity(
        history_path=str(tmp_path / "no.jsonl"), stats_path="/no/such.json"
    )
    assert s["recent_prompts"] == []
    assert s["latest_stats"]["available"] is False


def test_cc_activity_no_stats_cache(tmp_path):
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        '{"display": "x", "timestamp": 1000, "project": "/p/q", "sessionId": "s"}\n'
    )
    s = collectors.cc_activity(history_path=str(hist), stats_path="/no/such.json")
    assert s["latest_stats"]["available"] is False
    assert len(s["recent_prompts"]) == 1


def test_cc_activity_latest_stats(tmp_path):
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        '{"display": "x", "timestamp": 1000, "project": "/p/q", "sessionId": "s"}\n'
    )
    s = collectors.cc_activity(history_path=str(hist), stats_path=FIX)
    assert s["latest_stats"]["available"] is True
    assert s["latest_stats"]["date"]
    assert s["latest_stats"]["messages"] > 0


# ── activity_feed tests ──────────────────────────────────────────────────────

def _make_ops_log(tmp_path, entries):
    """Write JSONL ops log entries."""
    log = tmp_path / "ops.log"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(log)


def _make_history(tmp_path, entries):
    """Write JSONL history entries (cc prompts, timestamp in ms)."""
    hist = tmp_path / "history.jsonl"
    hist.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(hist)


def test_activity_feed_merge_order(tmp_path):
    log = _make_ops_log(tmp_path, [
        {"ts": "2026-01-01T00:00:10Z", "cmd": "run", "status": "success", "account": "a@b.com", "model": "", "prompt": "p1"},
        {"ts": "2026-01-01T00:00:30Z", "cmd": "run", "status": "success", "account": "a@b.com", "model": "", "prompt": "p2"},
    ])
    hist = _make_history(tmp_path, [
        {"display": "cc1", "timestamp": 1735689620000, "project": "/x/y", "sessionId": "s1"},  # epoch 1735689620
    ])
    result = collectors.activity_feed(log_path=log, history_path=hist, stats_path="/no/such.json")
    events = result["events"]
    assert len(events) == 3
    epochs = [e["ts_epoch"] for e in events]
    assert epochs == sorted(epochs, reverse=True)


def test_activity_feed_ts_normalize_iso(tmp_path):
    log = _make_ops_log(tmp_path, [
        {"ts": "2026-06-01T12:00:00Z", "cmd": "run", "status": "success", "account": "x", "model": "", "prompt": ""},
    ])
    result = collectors.activity_feed(log_path=log, history_path="/no/such.jsonl", stats_path="/no/such.json")
    ev = result["events"][0]
    assert ev["kind"] == "agy"
    assert ev["ts_epoch"] == 1780315200  # 2026-06-01T12:00:00Z


def test_activity_feed_ts_normalize_cc_ms(tmp_path):
    hist = _make_history(tmp_path, [
        {"display": "hello", "timestamp": 1748779200000, "project": "/p/q", "sessionId": "s"},
    ])
    result = collectors.activity_feed(log_path="/no/such.log", history_path=hist, stats_path="/no/such.json")
    ev = result["events"][0]
    assert ev["kind"] == "cc"
    assert ev["ts_epoch"] == 1748779200


def test_activity_feed_limit(tmp_path):
    entries = [
        {"ts": f"2026-01-01T00:00:{i:02d}Z", "cmd": "run", "status": "success", "account": "a", "model": "", "prompt": ""}
        for i in range(30)
    ]
    log = _make_ops_log(tmp_path, entries)
    result = collectors.activity_feed(limit=25, log_path=log, history_path="/no/such.jsonl", stats_path="/no/such.json")
    assert len(result["events"]) == 25
    # newest 25
    epochs = [e["ts_epoch"] for e in result["events"]]
    assert epochs == sorted(epochs, reverse=True)


def test_activity_feed_latest_stats_passthrough(tmp_path):
    hist = _make_history(tmp_path, [
        {"display": "x", "timestamp": 1000000, "project": "/p", "sessionId": "s"},
    ])
    result = collectors.activity_feed(log_path="/no/such.log", history_path=hist, stats_path=FIX)
    assert result["latest_stats"]["available"] is True
    assert result["latest_stats"]["messages"] > 0


def test_activity_feed_missing_files(tmp_path):
    result = collectors.activity_feed(
        log_path="/no/such.log", history_path="/no/such.jsonl", stats_path="/no/such.json"
    )
    assert result["events"] == []
    assert result["warning"] is not None


def test_activity_feed_malformed_ops_skip(tmp_path):
    log = tmp_path / "ops.log"
    log.write_text(
        'NOT JSON\n'
        '{"ts": "2026-01-01T00:00:01Z", "cmd": "run", "status": "success", "account": "a", "model": "", "prompt": "ok"}\n'
    )
    result = collectors.activity_feed(log_path=str(log), history_path="/no/such.jsonl", stats_path="/no/such.json")
    assert len(result["events"]) == 1
    assert result["events"][0]["prompt"] == "ok"


def test_activity_feed_ts_epoch_zero_fallback(tmp_path):
    log = tmp_path / "ops.log"
    log.write_text(
        '{"ts": "INVALID", "cmd": "run", "status": "success", "account": "a", "model": "", "prompt": "bad"}\n'
        '{"ts": "2026-01-01T00:00:01Z", "cmd": "run", "status": "success", "account": "a", "model": "", "prompt": "good"}\n'
    )
    result = collectors.activity_feed(log_path=str(log), history_path="/no/such.jsonl", stats_path="/no/such.json")
    events = result["events"]
    assert len(events) == 2
    # bad ts → ts_epoch=0, sorts to end
    assert events[-1]["prompt"] == "bad"
    assert events[-1]["ts_epoch"] == 0
    assert events[0]["prompt"] == "good"
