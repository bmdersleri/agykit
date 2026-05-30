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
