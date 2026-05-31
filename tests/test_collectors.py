import json
import os

import pytest

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
        "dashboard.collectors.subprocess.run",
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
        "dashboard.collectors.subprocess.run",
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
