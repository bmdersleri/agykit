import http.client
import json
import os
import sqlite3
import threading

import pytest

from dashboard import server

FIX = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "fixtures", "stats-cache.json"
)
FIXBRAIN = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "fixtures", "brain"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AGYKIT_DASH_STATS", FIX)
    monkeypatch.setenv("AGYKIT_DASH_BRAIN", FIXBRAIN)


def _boot():
    srv = server.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path)
    return c.getresponse()


def test_api_data_claude():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/data?source=claude&range=all")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["labels"] == ["2026-05-27", "2026-05-28", "2026-05-29"]
        assert data["tokens_total"] == [1500, 800, 2300]
    finally:
        srv.shutdown()


def test_api_data_agy():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/data?source=agy&range=all")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["labels"] == ["2026-05-28", "2026-05-29"]
        assert data["sessions"] == [1, 1]
    finally:
        srv.shutdown()


def test_api_bad_source():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/data?source=bogus&range=all")
        assert r.status == 400
    finally:
        srv.shutdown()


def test_index_served():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/")
        assert r.status == 200
        assert b"<canvas" in r.read()
    finally:
        srv.shutdown()


def test_unknown_404():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/nope")
        assert r.status == 404
    finally:
        srv.shutdown()


def test_events_first_line():
    srv = _boot()
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        c.request("GET", "/events")
        r = c.getresponse()
        assert r.status == 200
        assert r.headers["Content-Type"].startswith("text/event-stream")
        first = r.fp.readline()
        assert first.startswith(b"event:") or first.startswith(b"data:")
    finally:
        srv.shutdown()


def test_check_mtimes_maps_selective_refresh(monkeypatch, tmp_path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(home))

    server._MTIME_CACHE.clear()
    job_db = str(tmp_path / "jobs.db")
    quota_cache = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")
    statusline = os.path.expanduser("~/.gemini/antigravity-cli/statusline-latest.json")

    monkeypatch.setattr(
        server,
        "resolve_job_state",
        lambda: {
            "db_path": job_db,
            "state_dir": str(tmp_path / "state"),
            "socket_path": str(tmp_path / "sock"),
            "old_job_dir": str(tmp_path / "state" / "agykit-jobs"),
        },
    )

    changed = {
        job_db,
        quota_cache,
        statusline,
        os.path.expanduser("~/.claude/stats-cache.json"),
        os.path.expanduser("~/.claude/history.jsonl"),
        os.path.expanduser("~/.codex/history.jsonl"),
        os.path.expanduser("~/.codex/session_index.jsonl"),
        os.path.expanduser("~/.codex/state_5.sqlite"),
        os.path.join(str(project), ".agykit.conf"),
        os.path.join(str(project), "CLAUDE_AGY_SYSTEM.md"),
        os.path.join(str(project), "CODEX_AGY_SYSTEM.md"),
    }

    def fake_get_mtime(path):
        return 100.0 if path in changed else 0.0

    def fake_newest_glob(pattern):
        return 100.0 if "transcript_full.jsonl" in pattern else 0.0

    monkeypatch.setattr(server, "_get_mtime", fake_get_mtime)
    monkeypatch.setattr(server, "_newest_glob", fake_newest_glob)

    events = server._check_mtimes()

    assert {"job", "forecast", "recommendation", "agent-matrix"}.issubset(events)
    assert {"quota", "health"}.issubset(events)
    assert "claude" in events
    assert "codex" in events


# ---------------------------------------------------------------------------
# new widget endpoints
# ---------------------------------------------------------------------------


class _FakeProc:
    stdout = (
        "Total commands:    1\nTokens saved:      0K (0.0%)\nEfficiency meter: ░ 0.0%\n"
    )
    returncode = 0


def test_api_rtk_stats(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.rtk.subprocess.run",
        lambda *a, **kw: _FakeProc(),
    )
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/rtk-stats")
        assert r.status == 200
        data = json.loads(r.read())
        assert "tokens_saved" in data
        assert "efficiency_pct" in data
        assert "top_commands" in data
    finally:
        srv.shutdown()


def test_api_cc_activity(monkeypatch, tmp_path):
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        '{"display": "test", "timestamp": 1000, "project": "/p/q", "sessionId": "s"}\n'
    )
    monkeypatch.setenv("AGYKIT_DASH_HISTORY", str(hist))
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/cc-activity")
        assert r.status == 200
        data = json.loads(r.read())
        assert "recent_prompts" in data
        assert "latest_stats" in data
    finally:
        srv.shutdown()


def test_api_codex_usage(monkeypatch, tmp_path):
    hist = tmp_path / "history.jsonl"
    hist.write_text('{"session_id": "s", "ts": 1780299000, "text": "codex prompt"}\n')
    idx = tmp_path / "session_index.jsonl"
    idx.write_text(
        '{"id": "s", "thread_name": "Codex", "updated_at": "2026-06-01T07:30:00Z"}\n'
    )
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
    con.execute(
        """
        INSERT INTO threads
        (id, title, cwd, tokens_used, model, updated_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("s", "Codex", os.getcwd(), 1234, "gpt-5.5", 1780299000, 0),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("AGYKIT_DASH_CODEX_HISTORY", str(hist))
    monkeypatch.setenv("AGYKIT_DASH_CODEX_SESSION_INDEX", str(idx))
    monkeypatch.setenv("AGYKIT_DASH_CODEX_STATE", str(db))
    monkeypatch.setenv("AGYKIT_DASH_CODEX_PROJECT", os.getcwd())

    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/codex-usage")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["available"] is True
        assert "summary" in data
        assert "recent_prompts" in data
        assert data["summary"]["tokens_used"] == 1234
    finally:
        srv.shutdown()


def test_api_quota_alerts(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.agy_model_quota",
        lambda: {
            "accounts": [
                {
                    "email": "u@x.com",
                    "models": [
                        {
                            "model_id": "gemini-3.5-pro",
                            "display_name": "Gemini 3.5 Pro",
                            "remaining_fraction": 0.05,
                        }
                    ],
                    "error": None,
                }
            ],
            "warning": None,
        },
    )
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("AGYKIT_QUOTA_ALERT_PCT", "15")
        from dashboard import alerts as _dal

        monkeypatch.setattr(_dal, "_STATE_DEFAULT", os.path.join(td, "state.json"))
        monkeypatch.setattr(_dal, "_OPS_LOG_DEFAULT", os.path.join(td, "ops.log"))
        srv = _boot()
        try:
            r = _get(srv.server_address[1], "/api/quota-alerts")
            assert r.status == 200
            data = json.loads(r.read())
            assert "alerts" in data
        finally:
            srv.shutdown()


def test_api_health_route(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.health_status",
        lambda **kwargs: {
            "ok": True,
            "generated_at": "2026-06-03T12:00:00+00:00",
            "source": "agykit",
            "stale": False,
            "overall_status": "ok",
            "summary": {"passed": 1, "warnings": 0, "critical": 0},
            "checks": [],
        },
    )
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/health")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["ok"] is True
        assert data["overall_status"] == "ok"
    finally:
        srv.shutdown()


def test_api_active_job_timeline_route(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.job_timeline",
        lambda **kwargs: {
            "ok": True,
            "generated_at": "2026-06-03T12:00:00+00:00",
            "source": "agykit",
            "stale": False,
            "job_id": "jid-1",
            "snapshot": {"status": "running"},
            "timeline": [],
            "metrics": {"elapsed_seconds": 1},
            "warning": None,
        },
    )
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/active-job/timeline")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["job_id"] == "jid-1"
    finally:
        srv.shutdown()


def test_api_recommendation_route(monkeypatch):
    monkeypatch.setattr(
        "dashboard.collectors.recommended_account_model",
        lambda **kwargs: {
            "ok": True,
            "generated_at": "2026-06-03T12:00:00+00:00",
            "source": "agykit",
            "stale": False,
            "mode": kwargs.get("mode", "balanced"),
            "recommendation": {"account": "a@example.com", "model": "gemini-2.5-flash"},
            "alternatives": [],
            "rejected": [],
            "signals": {},
            "warning": None,
        },
    )
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/recommendation?mode=reliability")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["mode"] == "reliability"
        assert data["recommendation"]["account"] == "a@example.com"
    finally:
        srv.shutdown()


def test_api_version_route():
    srv = _boot()
    try:
        r = _get(srv.server_address[1], "/api/version")
        assert r.status == 200
        data = json.loads(r.read())
        assert data["ok"] is True
        assert data["version"] == "1.3.2"
        assert data["source"] == "agykit"
    finally:
        srv.shutdown()
