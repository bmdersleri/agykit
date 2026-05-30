# Quota Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Live localhost dashboard charting Claude Code + agy usage/activity history, launched via `agykit dash`.

**Architecture:** Python 3 stdlib HTTP server (`ThreadingHTTPServer`) serves a Chart.js page; two collector functions read existing local files (`~/.claude/stats-cache.json`, agy brain transcripts) into daily series; SSE pushes a refresh when source files change.

**Tech Stack:** Python 3.13 stdlib only (http.server, json, urllib, argparse, webbrowser). NO pip deps. Chart.js via CDN. Bash subcommand wiring. pytest for tests (dev-only).

**Hard constraints:** zero pip dependencies; bind 127.0.0.1 only; read-only on ~/.claude and ~/.gemini.

---

## File Structure

- Create `dashboard/__init__.py` — empty, makes package importable by tests.
- Create `dashboard/collectors.py` — `claude_series()`, `agy_series()`, range helper. Pure, stdlib.
- Create `dashboard/server.py` — routing, `/api/data`, `/events` SSE, argparse, browser open.
- Create `dashboard/index.html` — Chart.js page, vanilla JS.
- Create `dashboard/fixtures/stats-cache.json` — fake Claude data.
- Create `dashboard/fixtures/brain/<id>/.system_generated/logs/transcript_full.jsonl` — fake agy session (x2, one with a malformed line).
- Create `tests/test_collectors.py` — collector unit tests.
- Create `tests/test_server.py` — server smoke test.
- Modify `agykit` — add `cmd_dash`, dispatch `dash)`, usage() line.
- Modify `pyproject? NONE` — agykit has no pyproject; pytest runs via `python -m pytest` (see Task 7 verify). If a `[dev]` pytest config is desired, add a minimal `pyproject.toml` ONLY if tests need it; otherwise rely on repo's existing test runner in `tests/`.

Note: inspect existing `tests/` first to match how agykit currently runs tests (bash test harness vs pytest). Mirror it.

---

## Task 0: Scaffold + fixtures

**Files:**
- Create: `dashboard/__init__.py`, `dashboard/fixtures/stats-cache.json`,
  `dashboard/fixtures/brain/sess-a/.system_generated/logs/transcript_full.jsonl`,
  `dashboard/fixtures/brain/sess-b/.system_generated/logs/transcript_full.jsonl`

- [ ] **Step 1: empty package init**
  `dashboard/__init__.py` = empty file.

- [ ] **Step 2: fake Claude stats-cache fixture**
  `dashboard/fixtures/stats-cache.json`:
```json
{
  "version": 3,
  "lastComputedDate": "2026-05-29",
  "dailyActivity": [
    {"date": "2026-05-27", "messageCount": 100, "sessionCount": 3, "toolCallCount": 40},
    {"date": "2026-05-28", "messageCount": 50,  "sessionCount": 2, "toolCallCount": 20},
    {"date": "2026-05-29", "messageCount": 200, "sessionCount": 5, "toolCallCount": 80}
  ],
  "dailyModelTokens": [
    {"date": "2026-05-27", "tokensByModel": {"claude-opus-4-8": 1000, "claude-haiku-4-5-20251001": 500}},
    {"date": "2026-05-28", "tokensByModel": {"claude-opus-4-8": 800}},
    {"date": "2026-05-29", "tokensByModel": {"claude-opus-4-8": 2000, "claude-haiku-4-5-20251001": 300}}
  ]
}
```

- [ ] **Step 3: fake agy transcript fixtures**
  `sess-a/.../transcript_full.jsonl` (2 valid lines):
```
{"type":"USER_INPUT","created_at":"2026-05-28T10:00:00Z","content":"hi","model":"Gemini 3.5 Flash (Medium)","tool_calls":[]}
{"type":"RUN_COMMAND","created_at":"2026-05-28T10:01:00Z","tool_calls":[{"name":"run"}],"model":"Gemini 3.5 Flash (Medium)"}
```
  `sess-b/.../transcript_full.jsonl` (1 valid + 1 malformed line):
```
{"type":"PLANNER_RESPONSE","created_at":"2026-05-29T09:00:00Z","tool_calls":[{"name":"grep"},{"name":"view"}],"model":"Gemini 3.5 Flash (High)"}
{not valid json
```

- [ ] **Step 4: Commit**
```bash
git add dashboard/__init__.py dashboard/fixtures
git commit -m "test(dash): add quota-dashboard fixtures"
```

---

## Task 1: collectors.claude_series (TDD)

**Files:**
- Create: `dashboard/collectors.py`
- Test: `tests/test_collectors.py`

**Contract:**
```python
def claude_series(range_key: str = "all", *, stats_path: str | None = None) -> dict
# returns {"labels":[date,...], "tokens_total":[int,...],
#          "tokens_by_model":{model:[int,...]}, "messages":[int,...],
#          "sessions":[int,...], "tool_calls":[int,...], "warning": str|None}
# labels sorted ascending; per-model arrays aligned to labels (0 when absent).
# range_key in {"7d","30d","all"} filters by last N days relative to max label.
# Missing/unreadable file -> all arrays empty, warning set.
```

- [ ] **Step 1: failing test**
```python
import os
from dashboard import collectors
FIX = os.path.join(os.path.dirname(__file__), "..", "dashboard", "fixtures", "stats-cache.json")

def test_claude_series_all():
    s = collectors.claude_series("all", stats_path=FIX)
    assert s["labels"] == ["2026-05-27", "2026-05-28", "2026-05-29"]
    assert s["tokens_total"] == [1500, 800, 2300]
    assert s["tokens_by_model"]["claude-opus-4-8"] == [1000, 800, 2000]
    assert s["tokens_by_model"]["claude-haiku-4-5-20251001"] == [500, 0, 300]
    assert s["messages"] == [100, 50, 200]
    assert s["warning"] is None

def test_claude_series_missing_file():
    s = collectors.claude_series("all", stats_path="/no/such.json")
    assert s["labels"] == []
    assert s["warning"]
```

- [ ] **Step 2: run, expect fail** — `python -m pytest tests/test_collectors.py -v` → FAIL (no module/attr).
- [ ] **Step 3: implement `claude_series`** in `dashboard/collectors.py`. Default `stats_path = os.path.expanduser("~/.claude/stats-cache.json")` overridable. Parse JSON, build sorted label set from both arrays, align tokens/model/activity, apply range filter via shared `_apply_range(labels, range_key)`.
- [ ] **Step 4: run, expect pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(dash): claude_series collector"`.

---

## Task 2: collectors.agy_series (TDD)

**Files:** Modify `dashboard/collectors.py`; Test add to `tests/test_collectors.py`.

**Contract:**
```python
def agy_series(range_key: str = "all", *, brain_dir: str | None = None) -> dict
# scans <brain_dir>/*/.system_generated/logs/transcript_full.jsonl
# bucket by created_at date (UTC date part):
# returns {"labels":[...], "sessions":[int,...], "tool_calls":[int,...],
#          "model_mix":{model:[int,...]}, "warning": str|None, "skipped": int}
# sessions/day = count of distinct session dirs whose newest created_at falls on that date.
# tool_calls/day = sum len(tool_calls) across records on that date.
# model_mix = per-model record counts per date.
# malformed JSONL lines skipped, counted in "skipped"; reflected in warning when >0.
# missing/empty brain dir -> empty arrays, warning set.
```

- [ ] **Step 1: failing test**
```python
FIXBRAIN = os.path.join(os.path.dirname(__file__), "..", "dashboard", "fixtures", "brain")

def test_agy_series_buckets_and_skips():
    s = collectors.agy_series("all", brain_dir=FIXBRAIN)
    assert s["labels"] == ["2026-05-28", "2026-05-29"]
    assert s["sessions"] == [1, 1]
    assert s["tool_calls"] == [1, 2]   # sess-a: 1, sess-b: 2
    assert s["skipped"] == 1
    assert s["warning"]
```

- [ ] **Step 2: run, expect fail.**
- [ ] **Step 3: implement `agy_series`.** Default `brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain")`. Use `glob`. Per file: read lines, `json.loads` each, on error `skipped += 1; continue`. Date = `created_at[:10]`. Session-date = max created_at date in that file. Reuse `_apply_range`.
- [ ] **Step 4: run, expect pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(dash): agy_series collector"`.

---

## Task 3: range filter helper (TDD)

**Files:** Modify `dashboard/collectors.py`; test in `tests/test_collectors.py`.

**Contract:** `_apply_range(labels: list[str], range_key: str) -> list[str]` returns the sublist of labels within last 7/30 days of `max(labels)`; `"all"` returns labels unchanged; empty input -> empty.

- [ ] **Step 1: failing test**
```python
def test_apply_range_7d():
    labels = ["2026-05-20","2026-05-27","2026-05-28","2026-05-29"]
    assert collectors._apply_range(labels, "7d") == ["2026-05-27","2026-05-28","2026-05-29"]
    assert collectors._apply_range(labels, "all") == labels
    assert collectors._apply_range([], "7d") == []
```

- [ ] **Step 2: run fail. Step 3: implement (use datetime.date.fromisoformat). Step 4: pass. Step 5: commit** `git commit -m "feat(dash): range filter helper"`.

(If `_apply_range` already written in Task 1, move this test earlier and skip reimplementation — keep one definition.)

---

## Task 4: server routing + /api/data (TDD)

**Files:** Create `dashboard/server.py`; Test `tests/test_server.py`.

**Contract:** `make_server(host, port) -> ThreadingHTTPServer`. Handler routes:
- `GET /` → 200 `text/html`, body of `index.html`.
- `GET /api/data?source=claude|agy&range=7d|30d|all` → 200 `application/json`, body = collector dict. Bad `source` → 400 JSON `{"error":...}`.
- other → 404.
`argparse`: `--host 127.0.0.1`, `--port 8787`, `--no-open`. `main()` builds server, prints `http://host:port`, opens browser unless `--no-open`, `serve_forever()`.

- [ ] **Step 1: failing smoke test**
```python
import json, threading, http.client
from dashboard import server

def _boot():
    srv = server.make_server("127.0.0.1", 0)  # ephemeral port
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv

def test_api_data_claude(monkeypatch):
    import os
    fx = os.path.join(os.path.dirname(__file__), "..", "dashboard", "fixtures", "stats-cache.json")
    monkeypatch.setenv("AGYKIT_DASH_STATS", fx)   # server passes env override to collector
    srv = _boot(); port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port); c.request("GET", "/api/data?source=claude&range=all")
    r = c.getresponse(); assert r.status == 200
    data = json.loads(r.read()); assert data["labels"] == ["2026-05-27","2026-05-28","2026-05-29"]
    srv.shutdown()

def test_index_served():
    srv = _boot(); port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port); c.request("GET", "/")
    r = c.getresponse(); assert r.status == 200 and b"<canvas" in r.read()
    srv.shutdown()
```

- [ ] **Step 2: run fail.**
- [ ] **Step 3: implement `server.py`.** Collector path overrides read from env: `AGYKIT_DASH_STATS` → `claude_series(stats_path=...)`, `AGYKIT_DASH_BRAIN` → `agy_series(brain_dir=...)` (defaults to None → real paths). Serve `index.html` from `Path(__file__).parent`.
- [ ] **Step 4: run pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(dash): http server + /api/data"`.

---

## Task 5: SSE /events (TDD-lite)

**Files:** Modify `dashboard/server.py`; add test to `tests/test_server.py`.

**Contract:** `GET /events` → `text/event-stream`. Server tracks max mtime of stats file + newest brain transcript; loop every ~3 s, on change writes `data: refresh\n\n`. Send one immediate `data: hello\n\n` on connect so clients confirm wiring. Handle `BrokenPipeError` by returning from handler.

- [ ] **Step 1: failing test** — connect, read first event line, assert it starts with `data:`:
```python
def test_events_first_line():
    srv = _boot(); port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/events")
    r = c.getresponse(); assert r.status == 200
    assert r.headers["Content-Type"].startswith("text/event-stream")
    line = r.fp.readline(); assert line.startswith(b"data:")
    srv.shutdown()
```

- [ ] **Step 2: fail. Step 3: implement /events branch (set headers, flush immediate hello, then mtime-poll loop with self.wfile.flush()). Step 4: pass. Step 5: commit** `git commit -m "feat(dash): SSE live refresh"`.

---

## Task 6: index.html

**Files:** Create `dashboard/index.html`.

- [ ] **Step 1: build page** — single file. `<canvas id="main">` + `<canvas id="mix">`. Chart.js CDN `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`. Controls: source `<select>` (claude/agy), range `<select>` (7d/30d/all), a live dot `<span id="live">`. JS: `load()` fetches `/api/data?source=&range=`, renders line chart (tokens_total for claude / sessions for agy) + stacked bar (tokens_by_model / model_mix). `new EventSource('/events').onmessage = () => { flash #live; load(); }`. Show `data.warning` in a banner if set.
- [ ] **Step 2: manual check** — covered by Task 4 `test_index_served` (asserts `<canvas` present). Re-run `python -m pytest tests/test_server.py -v`.
- [ ] **Step 3: Commit** — `git commit -m "feat(dash): Chart.js dashboard page"`.

---

## Task 7: bash `agykit dash` wiring

**Files:** Modify `agykit`.

- [ ] **Step 1: add `cmd_dash`** near other `cmd_*`:
```bash
cmd_dash() {
    local dir; dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dashboard"
    [ -f "$dir/server.py" ] || { echo "dashboard not found at $dir" >&2; exit 1; }
    exec python3 "$dir/server.py" "$@"
}
```
- [ ] **Step 2: dispatch** — in the `case "${1:-}"` block add: `dash)          cmd_dash "${@:2}" ;;`
- [ ] **Step 3: usage()** — add line: `  agykit dash [--port N]          Open the usage dashboard (localhost)`
- [ ] **Step 4: verify dispatch** — `bash agykit --help | grep dash` shows the line; `bash agykit dash --no-open --port 8788 &` then `curl -s 127.0.0.1:8788/api/data?source=claude\&range=7d` returns JSON; kill it.
- [ ] **Step 5: Commit** — `git commit -m "feat: agykit dash subcommand"`.

---

## Task 8: full verify + docs

**Files:** Modify `README.md` (add `agykit dash` to command list).

- [ ] **Step 1: run full test suite** — match agykit's existing runner. If pytest: `python -m pytest tests/ -v` → all pass. Also run existing bash tests in `tests/` unchanged → pass.
- [ ] **Step 2: lint sanity** — `python -m py_compile dashboard/server.py dashboard/collectors.py`.
- [ ] **Step 3: README** — add one line under usage documenting `agykit dash`.
- [ ] **Step 4: Commit** — `git commit -m "docs: document agykit dash"`.

---

## Acceptance criteria

- `agykit dash` opens a browser dashboard at `127.0.0.1:8787`.
- Claude line chart shows daily tokens; stacked bar shows tokens-by-model; range 7d/30d/all works.
- agy view shows sessions/day, tool-calls/day, model mix from brain transcripts.
- Page auto-refreshes (SSE) when `stats-cache.json` or a brain transcript changes.
- Empty/missing data → "no data" banner, no crash.
- All tests pass; existing agykit tests unaffected; zero pip dependencies added.

## Self-review notes

- Spec coverage: collectors (Claude+agy) ✓ T1/T2, server+routes ✓ T4, SSE ✓ T5, page ✓ T6, bash subcommand ✓ T7, error handling ✓ (missing-file/malformed/400/404 across T1/T2/T4), tests ✓ T1-T5/T8, zero-dep ✓ constraint enforced.
- `_apply_range` defined once (Task 1 or 3 — keep single definition; Task 3 note covers ordering).
- Env overrides `AGYKIT_DASH_STATS` / `AGYKIT_DASH_BRAIN` consistent between server (T4/T5) and collectors (T1/T2 signatures accept `stats_path`/`brain_dir`).
