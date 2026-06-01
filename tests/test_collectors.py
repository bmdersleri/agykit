import json
import os
import sqlite3


from dashboard import collectors
import dashboard.collectors.agy as agy_collectors

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


def test_claude_quota_normalizes_fraction_utilization(monkeypatch, tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"five_hour": {"utilization": 0.64}}).encode()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **kw: _Resp(),
    )

    result = collectors.claude_quota(creds_path=str(creds))
    quota = result["quotas"][0]

    assert quota["utilization"] == 64
    assert quota["pct_remaining"] == 36


def test_claude_quota_normalizes_percent_utilization(monkeypatch, tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"five_hour": {"utilization": 100}}).encode()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **kw: _Resp(),
    )

    result = collectors.claude_quota(creds_path=str(creds))
    quota = result["quotas"][0]

    assert quota["utilization"] == 100
    assert quota["pct_remaining"] == 0


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


def test_agy_quota_status_enriches_saved_accounts(monkeypatch, tmp_path):
    home = tmp_path / "home"
    accounts_dir = home / ".gemini" / "accounts"
    accounts_dir.mkdir(parents=True)
    (accounts_dir / "pro@example.com.json").write_text(
        json.dumps({"token": {"refresh_token": "rt-pro"}})
    )
    (accounts_dir / "free@example.com.json").write_text(
        json.dumps({"token": {"refresh_token": "rt-free"}})
    )
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "cli-20260601_120000.log").write_text(
        "I0601 12:00:00.000000 email=pro@example.com\n"
        "E0601 12:00:01.000000 RESOURCE_EXHAUSTED Resets in 1h\n"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        agy_collectors,
        "_refresh_access_token",
        lambda refresh_token: "access-" + refresh_token,
    )
    monkeypatch.setattr(
        agy_collectors,
        "_google_userinfo",
        lambda access_token: {
            "name": access_token,
            "picture": "https://example.com/" + access_token + ".png",
        },
    )
    monkeypatch.setattr(
        agy_collectors,
        "_load_plans_cache",
        lambda: {"pro@example.com": "Google AI Pro"},
    )
    monkeypatch.setattr(agy_collectors, "_save_profile", lambda email, name, picture: None)

    result = collectors.agy_quota_status(log_dir=str(log_dir))
    by_email = {a["email"]: a for a in result["accounts"]}

    assert set(by_email) == {"pro@example.com", "free@example.com"}
    assert by_email["pro@example.com"]["is_pro"] is True
    assert by_email["free@example.com"]["is_pro"] is False
    assert by_email["pro@example.com"]["picture"].endswith("access-rt-pro.png")
    assert by_email["free@example.com"]["picture"].endswith("access-rt-free.png")
    assert by_email["free@example.com"]["status"] == "available"


def test_agy_quota_status_uses_cached_profile_on_userinfo_failure(monkeypatch, tmp_path):
    home = tmp_path / "home"
    accounts_dir = home / ".gemini" / "accounts"
    accounts_dir.mkdir(parents=True)
    (accounts_dir / "cached@example.com.json").write_text(
        json.dumps({"token": {"refresh_token": "rt"}})
    )
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "cli-20260601_120000.log").write_text(
        "I0601 12:00:00.000000 email=cached@example.com\n"
        "E0601 12:00:01.000000 RESOURCE_EXHAUSTED Resets in 1h\n"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        agy_collectors,
        "_load_profiles_cache",
        lambda: {
            "cached@example.com": {
                "name": "Cached User",
                "picture": "https://example.com/cached.png",
            }
        },
    )
    monkeypatch.setattr(
        agy_collectors,
        "_refresh_access_token",
        lambda refresh_token: (_ for _ in ()).throw(OSError("offline")),
    )
    monkeypatch.setattr(agy_collectors, "_load_plans_cache", lambda: {})

    result = collectors.agy_quota_status(log_dir=str(log_dir))
    acct = result["accounts"][0]

    assert acct["name"] == "Cached User"
    assert acct["picture"] == "https://example.com/cached.png"
    assert acct["_avatar_err"] == "offline"


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


# ---------------------------------------------------------------------------
# codex_usage
# ---------------------------------------------------------------------------


def _make_codex_state(tmp_path, rows):
    db = tmp_path / "state_5.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE threads (
            id TEXT,
            title TEXT,
            cwd TEXT,
            tokens_used INTEGER,
            model TEXT,
            updated_at INTEGER,
            archived INTEGER
        )
        """
    )
    con.executemany(
        """
        INSERT INTO threads
        (id, title, cwd, tokens_used, model, updated_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()
    return str(db)


def test_codex_usage_parse(tmp_path):
    project = tmp_path / "agykit"
    project.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps({"session_id": "s1", "ts": 1780299000, "text": "first"}) + "\n"
        + json.dumps({"session_id": "s2", "ts": 1780299100, "text": "second"}) + "\n"
    )
    session_index = tmp_path / "session_index.jsonl"
    session_index.write_text(
        json.dumps({
            "id": "s2",
            "thread_name": "Second",
            "updated_at": "2026-06-01T07:31:40Z",
        }) + "\n"
    )
    state = _make_codex_state(tmp_path, [
        ("s1", "First", str(project), 1000, "gpt-5.5", 1780299000, 0),
        ("s2", "Second", str(other), 2000, "gpt-5.5", 1780299100, 0),
        ("old", "Archived", str(project), 9999, "gpt-5.5", 1, 1),
    ])

    s = collectors.codex_usage(
        history_path=str(history),
        session_index_path=str(session_index),
        state_path=state,
        project_path=str(project),
    )

    assert s["available"] is True
    assert s["summary"]["sessions"] == 2
    assert s["summary"]["prompts"] == 2
    assert s["summary"]["tokens_used"] == 3000
    assert s["summary"]["models"] == ["gpt-5.5"]
    assert s["current_project"]["sessions"] == 1
    assert s["current_project"]["tokens_used"] == 1000
    assert s["recent_prompts"][0]["text"] == "second"
    assert s["recent_threads"][0]["title"] == "Second"


def test_codex_status_from_auth(tmp_path):
    auth = tmp_path / "auth.json"
    # Create a fake JWT with a real-looking payload
    import base64, json
    payload = base64.urlsafe_b64encode(json.dumps({
        "https://api.openai.com/auth": {
            "chatgpt_plan_type": "plus",
            "chatgpt_account_id": "acct_123",
            "chatgpt_user_id": "user_456",
            "chatgpt_subscription_active_until": "2026-07-01T00:00:00+00:00",
        },
        "https://api.openai.com/profile": {
            "email": "test@example.com",
        },
    }).encode()).rstrip(b"=").decode()
    fake_jwt = f"header.{payload}.signature"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": fake_jwt},
    }))
    result = collectors.codex_status(auth_path=str(auth), state_path=str(tmp_path / "no-state.sqlite"))
    assert result["available"] is True
    assert result["account"]["plan_type"] == "plus"
    assert result["account"]["email"] == "test@example.com"
    assert result["account"]["account_id"] == "acct_123"


def test_codex_status_missing_files(tmp_path):
    result = collectors.codex_status(
        auth_path=str(tmp_path / "no-auth.json"),
        state_path=str(tmp_path / "no-state.sqlite"),
    )
    assert result["available"] is False
    assert result["account"] is None


def test_codex_status_from_state(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"auth_mode": "local", "tokens": {"access_token": ""}}))
    state = tmp_path / "state_5.sqlite"
    import sqlite3
    con = sqlite3.connect(str(state))
    con.execute("""
        CREATE TABLE threads (
            id TEXT, title TEXT, cwd TEXT, tokens_used INTEGER,
            model TEXT, updated_at INTEGER, archived INTEGER
        )
    """)
    con.execute(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "Test", "/home/test", 5000, "gpt-5.5", 1780299000, 0),
    )
    con.commit()
    con.close()
    result = collectors.codex_status(auth_path=str(auth), state_path=str(state))
    assert result["available"] is True
    assert result["thread_count"] == 1
    assert result["total_tokens_used"] == 5000
    assert result["current_model"] == "gpt-5.5"


def test_codex_usage_missing_files(tmp_path):
    s = collectors.codex_usage(
        history_path=str(tmp_path / "no-history.jsonl"),
        session_index_path=str(tmp_path / "no-index.jsonl"),
        state_path=str(tmp_path / "no-state.sqlite"),
        project_path=str(tmp_path),
    )
    assert s["available"] is False
    assert s["recent_prompts"] == []
    assert s["summary"]["sessions"] == 0
    assert s["warning"]


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


# ── Job state tests ─────────────────────────────────────────────────────────

def _job_db_path(tmp_path):
    return str(tmp_path / "jobs.db")

def test_job_create_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_snapshot
    jid = job_create("test-cmd", "test prompt")
    assert jid
    assert "T" in jid
    snap = job_snapshot(jid)
    assert snap is not None
    assert snap["job_id"] == jid
    assert snap["command"] == "test-cmd"
    assert snap["status"] == "starting"
    assert snap["prompt"] == "test prompt"
    assert snap["started_at"] is not None


def test_job_event_updates_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    jid = job_create("run", "hello")
    job_event(jid, "account_selected", "running", "trying a@b.com", account="a@b.com")
    snap = job_snapshot(jid)
    assert snap["status"] == "running"
    assert snap["stage"] == "trying a@b.com"
    assert snap["account"] == "a@b.com"


def test_job_event_with_error(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    jid = job_create("run", "hello")
    job_event(jid, "job_failed", "failed", "error", error="Something broke")
    snap = job_snapshot(jid)
    assert snap["status"] == "failed"
    assert snap["last_error"] == "Something broke"
    assert snap["ended_at"] is not None


def test_job_event_duration_and_category(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    import time
    jid = job_create("run", "duration test")
    time.sleep(0.05)
    job_event(jid, "job_failed", "failed", "error", error="403 quota exceeded reached")
    snap = job_snapshot(jid)
    assert snap["duration_seconds"] is not None
    assert snap["duration_seconds"] > 0
    assert snap["error_category"] == "quota"
    assert snap["error_detail"] == "403 quota exceeded reached"


def test_job_event_duration_non_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    jid = job_create("run", "no duration")
    job_event(jid, "account_selected", "running", "trying", account="a@b.com")
    snap = job_snapshot(jid)
    assert snap["duration_seconds"] is None


def test_job_event_error_detail_full(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    long_error = "x" * 500
    jid = job_create("run", "detail test")
    job_event(jid, "job_failed", "failed", "error", error=long_error)
    snap = job_snapshot(jid)
    assert snap["error_detail"] == long_error


def test_job_event_error_category_taxonomy(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot, _classify_error
    assert _classify_error("RESOURCE_EXHAUSTED quota") == "quota"
    assert _classify_error("request timed out") == "timeout"
    assert _classify_error("Connection refused") == "network"
    assert _classify_error("unauthorized token") == "auth"
    assert _classify_error("VERIFICATION FAILED") == "verify"
    assert _classify_error("some random error") is None
    assert _classify_error(None) is None
    assert _classify_error("") is None


def test_job_event_category_integration(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    cases = [
        ("rate limit exceeded", "quota"),
        ("timed out", "timeout"),
        ("ConnectionError: reset by peer", "network"),
        ("access_denied", "auth"),
        ("verify failed", "verify"),
    ]
    for error_text, expected_cat in cases:
        jid = job_create("run", f"cat-{expected_cat}")
        job_event(jid, "job_failed", "failed", "error", error=error_text)
        snap = job_snapshot(jid)
        assert snap["error_category"] == expected_cat, f"Expected {expected_cat} for '{error_text}', got {snap['error_category']}"


def test_job_event_schema_migration(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import _get_db
    conn = _get_db()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    conn.close()
    assert "duration_seconds" in cols
    assert "error_detail" in cols
    assert "error_category" in cols


def test_job_event_schema_migration_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import _get_db
    conn1 = _get_db()
    conn1.close()
    conn2 = _get_db()
    cols = [row[1] for row in conn2.execute("PRAGMA table_info(jobs)").fetchall()]
    conn2.close()
    assert "duration_seconds" in cols


def test_job_stats_success_rate(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_stats
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    jid1 = job_create("run", "a")
    job_event(jid1, "job_succeeded", "succeeded", "done")
    jid2 = job_create("run", "b")
    job_event(jid2, "job_failed", "failed", "error", error="boom")
    stats = job_stats()
    assert stats["total"] >= 2
    assert stats["success_rate_24h"] is not None
    assert 0 <= stats["success_rate_24h"] <= 100


def test_job_stats_avg_duration(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_stats
    jid = job_create("run", "dur")
    job_event(jid, "job_succeeded", "succeeded", "done")
    stats = job_stats()
    assert "avg_duration_seconds" in stats


def test_job_stats_error_breakdown(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_stats
    jid1 = job_create("run", "q")
    job_event(jid1, "job_failed", "failed", "error", error="quota exceeded")
    jid2 = job_create("run", "t")
    job_event(jid2, "job_failed", "failed", "error", error="timed out")
    stats = job_stats()
    assert "error_breakdown" in stats
    assert stats["error_breakdown"].get("quota", 0) >= 1


def test_job_stats_daily_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_stats
    jid = job_create("run", "daily")
    job_event(jid, "job_succeeded", "succeeded", "done")
    stats = job_stats()
    assert "daily_counts" in stats
    assert isinstance(stats["daily_counts"], dict)


def test_job_stats_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_stats
    stats = job_stats()
    assert stats["total"] == 0
    assert stats["success_rate_24h"] is None
    assert stats["avg_duration_seconds"] is None


def test_job_events_ordering(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_events
    jid = job_create("run", "test")
    job_event(jid, "account_selected", "running", "acct1", account="a@b.com")
    job_event(jid, "quota_rotated", "rotating", "rotate", account="a@b.com")
    job_event(jid, "job_succeeded", "succeeded", "done", account="a@b.com")
    events = job_events(jid)
    assert len(events) == 4  # job_started + 3 events
    assert events[0]["event"] == "job_started"
    assert events[1]["event"] == "account_selected"
    assert events[2]["event"] == "quota_rotated"
    assert events[3]["event"] == "job_succeeded"


def test_job_list_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_list
    assert job_list() == []


def test_job_list_orders_by_newest(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_list
    import time
    jid1 = job_create("run", "first")
    time.sleep(1.01)
    jid2 = job_create("run", "second")
    jobs = job_list()
    assert len(jobs) == 2
    assert jobs[0]["job_id"] == jid2
    assert jobs[1]["job_id"] == jid1


def test_job_snapshot_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_snapshot
    assert job_snapshot("nonexistent") is None


def test_job_events_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_events
    jid = job_create("run", "test")
    for i in range(10):
        job_event(jid, "account_selected", "running", f"step{i}")
    events = job_events(jid, limit=3)
    assert len(events) == 3
    assert events[-1]["stage"] == "step9"


def test_job_set_verify_result(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_set_verify_result, job_snapshot
    jid = job_create("do-escalate", "test")
    job_set_verify_result(jid, "passed")
    snap = job_snapshot(jid)
    assert snap["verify_result"] == "passed"


# ── SQLite-specific tests ──────────────────────────────────────────────────

def test_job_db_created(tmp_path, monkeypatch):
    dbp = _job_db_path(tmp_path)
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", dbp)
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_list
    assert not os.path.isfile(dbp)
    job_create("run", "first contact")
    assert os.path.isfile(dbp)


def test_job_concurrent_write(tmp_path, monkeypatch):
    dbp = _job_db_path(tmp_path)
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", dbp)
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_snapshot
    import threading
    jid = job_create("run", "concurrent")
    errors = []
    def _write():
        try:
            job_event(jid, "account_selected", "running", "step", account="a@b.com")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=_write) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"Concurrent writes failed: {errors}"
    snap = job_snapshot(jid)
    assert snap["account"] == "a@b.com"


def test_job_query_by_status(tmp_path, monkeypatch):
    dbp = _job_db_path(tmp_path)
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", dbp)
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_list
    jid = job_create("run", "test")
    job_event(jid, "job_succeeded", "succeeded", "done")
    jobs = job_list()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "succeeded"


def test_job_migration_from_json(tmp_path, monkeypatch):
    old_dir = tmp_path / "agykit-jobs"
    old_dir.mkdir()
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(old_dir))
    dbp = _job_db_path(tmp_path)
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", dbp)
    from dashboard.collectors.jobs import job_list
    import json, uuid
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc)
    jid = f"{ts.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    snap = {"job_id": jid, "command": "run", "status": "succeeded", "stage": "done",
            "prompt": "migrated", "started_at": ts.isoformat(), "updated_at": ts.isoformat()}
    (old_dir / f"{jid}.json").write_text(json.dumps(snap))
    ev = {"job_id": jid, "ts": ts.isoformat(), "event": "job_started", "status": "starting",
          "stage": "starting", "message": "migrated"}
    (old_dir / f"{jid}.events.jsonl").write_text(json.dumps(ev) + "\n")
    jobs = job_list()
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == jid
    assert jobs[0]["prompt"] == "migrated"


def test_notify_socket_noop_when_socket_missing(monkeypatch):
    from dashboard.collectors.jobs import _notify_socket
    _notify_socket({"event": "test"})  # should not raise


def test_notify_socket_delivers_event(tmp_path, monkeypatch):
    import socket, json, threading, time
    sock_path = str(tmp_path / "test-jobs.sock")
    monkeypatch.setattr("dashboard.collectors.jobs._JOB_SOCKET", sock_path)
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH",
                        _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR",
                        str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event

    received = []
    def _server():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(sock_path)
        s.settimeout(3.0)
        try:
            data = s.recv(4096)
            received.append(json.loads(data.decode("utf-8")))
        except socket.timeout:
            pass
        finally:
            s.close()
    t = threading.Thread(target=_server, daemon=True)
    t.start()
    time.sleep(0.2)

    jid = job_create("test-socket")
    job_event(jid, "job_succeeded", "succeeded", "done", account="a@b.com")
    t.join(timeout=2)
    assert len(received) == 1
    ev = received[0]
    assert ev["job_id"] == jid
    assert ev["event"] == "job_succeeded"
    assert ev["status"] == "succeeded"


# ── Stale detection / cancel tests ───────────────────────────────────────────

def test_recover_stale_jobs_marks_old_active(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_list
    jid = job_create("run", "stale")
    # Manually age the job so it appears stale
    import sqlite3
    conn = sqlite3.connect(_job_db_path(tmp_path))
    conn.execute(
        "UPDATE jobs SET updated_at='2000-01-01T00:00:00' WHERE job_id=?",
        (jid,),
    )
    conn.commit()
    conn.close()

    jobs = job_list()
    snap = next((j for j in jobs if j["job_id"] == jid), None)
    assert snap is not None
    assert snap["status"] == "blocked"
    assert snap["stage"] == "recovered"


def test_recover_stale_jobs_skips_recent(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    monkeypatch.setattr("dashboard.collectors.jobs.JOB_STALE_TIMEOUT", 3600)
    from dashboard.collectors.jobs import job_create, job_list
    jid = job_create("run", "recent")
    jobs = job_list()
    snap = next((j for j in jobs if j["job_id"] == jid), None)
    assert snap is not None
    assert snap["status"] == "starting"


def test_job_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_cancel, job_snapshot, job_events
    jid = job_create("run", "cancel-me")
    job_cancel(jid, "Test cancel")
    snap = job_snapshot(jid)
    assert snap["status"] == "blocked"
    assert snap["stage"] == "cancelled"
    assert snap["ended_at"] is not None
    events = job_events(jid)
    last = events[-1]
    assert last["event"] == "job_blocked"


# ── Prune tests ──────────────────────────────────────────────────────────────

def test_job_prune_older_than(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_list, job_prune
    import time
    jid1 = job_create("run", "old")
    time.sleep(1.01)
    jid2 = job_create("run", "new")
    # First job should be older than 1s
    removed = job_prune(older_than_seconds=1, dry_run=True)
    assert removed >= 1
    removed = job_prune(older_than_seconds=1)
    assert removed >= 1
    jobs = job_list()
    assert all(j["job_id"] == jid2 for j in jobs)


def test_job_prune_status_filter(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_prune, job_list
    jid1 = job_create("run", "will-succeed")
    jid2 = job_create("run", "will-fail")
    job_event(jid1, "job_succeeded", "succeeded", "done")
    job_event(jid2, "job_failed", "failed", "error", error="boom")
    removed = job_prune(status_filter="succeeded")
    assert removed == 1
    jobs = job_list(limit=100)
    ids = {j["job_id"] for j in jobs}
    assert jid1 not in ids
    assert jid2 in ids


def test_job_prune_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_prune
    jid = job_create("run", "test")
    removed = job_prune(older_than_seconds=0, dry_run=True)
    assert removed == 1
    # Job still exists
    from dashboard.collectors.jobs import job_snapshot
    assert job_snapshot(jid) is not None


def test_job_prune_max_count(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_list, job_prune
    jids = []
    for _ in range(5):
        jids.append(job_create("run", "test"))
        import time; time.sleep(0.1)
    job_prune(max_count=3, dry_run=False)
    jobs = job_list(limit=100)
    assert len(jobs) <= 3


# ── Filter / stats tests ────────────────────────────────────────────────────

def test_job_list_filter_status(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_list
    jid1 = job_create("run", "a")
    jid2 = job_create("run", "b")
    job_event(jid1, "job_succeeded", "succeeded", "done")
    succeeded = job_list(status="succeeded")
    starting = job_list(status="starting")
    assert any(j["job_id"] == jid1 for j in succeeded)
    assert any(j["job_id"] == jid2 for j in starting)


def test_job_list_filter_command(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_list
    jid1 = job_create("run", "x")
    jid2 = job_create("do-escalate", "y")
    runs = job_list(command="run")
    assert any(j["job_id"] == jid1 for j in runs)
    assert not any(j["job_id"] == jid2 for j in runs)


def test_job_stats_returns_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("dashboard.collectors.jobs.DB_PATH", _job_db_path(tmp_path))
    monkeypatch.setattr("dashboard.collectors.jobs._OLD_JSON_DIR", str(tmp_path / "no-such-dir"))
    from dashboard.collectors.jobs import job_create, job_event, job_stats
    for _ in range(3):
        jid = job_create("run", "x")
        job_event(jid, "job_succeeded", "succeeded", "done")
    s = job_stats()
    assert s["total"] >= 3
    assert s["by_status"].get("succeeded", 0) >= 3
    assert "last_24h" in s
