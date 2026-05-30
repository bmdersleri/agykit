import http.client
import json
import os
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
        assert r.fp.readline().startswith(b"data:")
    finally:
        srv.shutdown()
