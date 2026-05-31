# Design: Hardening & Observability

**Date:** 2026-05-31
**Status:** Approved
**Scope:** Three cohesive phases — CI, collectors module split, quota alerting

---

## Overview

Three improvements that harden the project and add proactive observability:

1. **CI** — automated test + lint on every push/PR (currently nothing runs the suites)
2. **Collectors split** — break the 1200-line `collectors.py` god-module into focused submodules
3. **Quota alerting** — proactive warning when an account nears quota exhaustion

Order matters: Phase 2 (split) makes Phase 3 (`alerts.py` imports collectors) clean. Phase 1 is independent and ships first.

### Constraints (carried from CLAUDE.md)

- Zero pip dependencies in runtime code — Python 3 stdlib only (`subprocess`, `urllib`, `json`, `os`, `glob`, `datetime`, `re`)
- `agykit` bash style preserved: `cmd_*` functions + dispatch case
- Web layer stays vanilla JS/HTML/CSS
- Dashboard binds `127.0.0.1` only; read-only on `~/.claude` and `~/.gemini` (alert state file is the one new write target, under `~/.gemini/`)

---

## Phase 1 — CI

### File: `.github/workflows/ci.yml`

- **Triggers:** `push` (all branches) + `pull_request`
- **Runner:** `ubuntu-latest`, Python `3.11`
- **Steps:**
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` (python-version 3.11)
  3. `pip install ruff pytest` (CI-only tooling, not runtime deps)
  4. `ruff check dashboard tests`
  5. `python3 -m pytest tests -q`
  6. `bash tests/run.sh`

### Bash test CI-safety

`tests/run.sh` orchestrates `test_git_safety.sh` + `test_do_escalate.sh`. Some assertions need a real `agy` binary / keyring, absent in CI.

- Add an env guard: tests requiring `agy` check `command -v agy` (or `AGYKIT_CI` env) and **skip with a printed `SKIP:` line** rather than fail.
- `tests/run.sh` exits non-zero only on real failures, not skips.
- Git-safety tests (snapshot/rollback logic) run fully — they only need `git`.

### README fix

README references `localhost:8787` in some places and the default port is `8787` (server.py `--port` default). Audit README + CLAUDE.md for port consistency; standardize on `8787` as the documented default (the `7373` used in dev is just an override example). Fix any mismatch.

### Success criteria

- CI green on a clean push
- A deliberately broken test fails CI (verified once, then reverted)

---

## Phase 2 — Collectors split

### Target structure

```
dashboard/collectors/
  __init__.py     # re-exports ALL public names — backward compat
  _common.py      # _apply_range + shared regex/constants used by >1 module
  agy.py          # agy_series, agy_quota_status, agy_statusline_snapshot,
                  #   agy_last_session, agy_model_quota, agy_model_quota_tmux,
                  #   agy_model_quota_cached, agy_refresh_all_accounts,
                  #   agy_active_account, _refresh_access_token, _google_userinfo,
                  #   _load_plans_cache, _save_plan, _fetch_quota_reset_times
  claude.py       # claude_series, claude_quota, cc_activity
  rtk.py          # rtk_stats, _parse_suffix, _ROW_RE
  ops.py          # ops_log
```

### Backward compatibility (critical)

`dashboard/collectors.py` becomes `dashboard/collectors/__init__.py`. The `__init__.py` re-exports every public function:

```python
from ._common import _apply_range
from .agy import (agy_series, agy_quota_status, agy_statusline_snapshot, ...)
from .claude import (claude_series, claude_quota, cc_activity)
from .rtk import rtk_stats
from .ops import ops_log
```

**Every existing import path must keep working unchanged:**
- `collectors.rtk_stats`, `collectors.cc_activity`, `collectors.claude_series`, etc.
- `server.py` imports unchanged
- `tests/test_collectors.py` + `tests/test_server.py` unchanged
- The `dashboard.collectors.subprocess` monkeypatch target in tests must still resolve — `subprocess` is imported in `rtk.py`; tests patch `dashboard.collectors.subprocess`. **Resolution:** re-export `subprocess` is not enough for `monkeypatch.setattr("dashboard.collectors.subprocess.run", ...)` because the patched module attribute must be the one `rtk_stats` actually uses. Update the test patch target to `dashboard.collectors.rtk.subprocess.run`, OR keep `rtk_stats` referencing a module-level `subprocess` that `__init__` also exposes. **Decision:** update test patch targets to the submodule (`dashboard.collectors.rtk.subprocess`) — this is the honest target and a one-line test edit, allowed since it does not weaken the assertion.

### Migration mechanics

- Move code verbatim into submodules; do not refactor logic during the move
- `server.py` cache-invalidation block (deletes `dashboard.collectors` from `sys.modules`) must also clear submodules — extend it to pop any `dashboard.collectors.*` key
- Run full suite after move; 19 tests must stay green (plus the patched-target edits)

### Success criteria

- All existing tests pass (with the documented test-patch-target edit)
- No file in `dashboard/collectors/` exceeds ~400 lines
- `import dashboard.collectors as c; c.rtk_stats` resolves

---

## Phase 3 — Quota alerting

### New module: `dashboard/alerts.py`

#### `check_quota_alerts(threshold_pct, *, state_path=None, channels=None) -> dict`

- Calls `collectors.agy_model_quota()` to get per-account per-model quota
- Finds models where `remaining_fraction < (threshold_pct / 100)`
- Groups by account; builds alert messages like
  `⚠ ismkirphone@gmail.com — Gemini 3.5 Pro %8 kaldı`
- Applies cooldown dedup (see below)
- Fires each enabled channel (best-effort, exceptions swallowed)
- Returns `{"alerts": [...], "fired": ["log","desktop"], "skipped_cooldown": [...], "warning": None}`

#### Cooldown / dedup

- State file: `~/.gemini/agykit-alert-state.json` (override via `state_path` for tests)
- Shape: `{"<email>:<model_id>": <last_alert_epoch>}`
- An alert fires only if `now - last_alert > AGYKIT_ALERT_COOLDOWN` (default 3600s)
- After firing, update state timestamp
- Corrupt/missing state file → treat as empty (alert fires)

#### Channels (each independent, graceful skip)

| Channel | Enabled when | Mechanism | Skip behavior |
|---------|-------------|-----------|---------------|
| `log` | always | append JSONL to `~/.gemini/agykit-ops.log`, `{ts, cmd:"alert", status:"quota-alert", account, model, prompt:<msg>}` | n/a |
| `desktop` | `notify-send` on PATH | `subprocess.run(["notify-send", title, body], timeout=5)` | binary absent → skip silently |
| `telegram` | `AGYKIT_TG_BOT_TOKEN` + `AGYKIT_TG_CHAT_ID` set | stdlib `urllib` POST to `https://api.telegram.org/bot<token>/sendMessage` | env unset → skip |

Channel selection is automatic from config presence; `log` always on. An explicit `channels` arg (list) overrides auto-detection for tests.

#### CLI entry point

`python3 -m dashboard.alerts check` → runs `check_quota_alerts()` with config-derived threshold, prints a one-line summary, exit 0 always (never breaks the caller).

### Config additions

`.agykit.conf` + `agykit.conf.example` + CLAUDE.md config table:

| Variable | Meaning | Default |
|----------|---------|---------|
| `AGYKIT_QUOTA_ALERT_PCT` | alert threshold (% remaining) | `15` |
| `AGYKIT_ALERT_COOLDOWN` | seconds between repeat alerts per model | `3600` |
| `AGYKIT_TG_BOT_TOKEN` | Telegram bot token (enables telegram channel) | — |
| `AGYKIT_TG_CHAT_ID` | Telegram chat id | — |

### Bash integration

In `agykit`, after `cmd_run` and `cmd_do_escalate` complete their main work:

```bash
python3 -m dashboard.alerts check >/dev/null 2>&1 || true
```

- Non-blocking, best-effort — alert failure never affects the run's exit code
- Resolve the dashboard module path relative to the agykit install dir (same mechanism existing code uses to locate `dashboard/`)

### Server integration

- New endpoint `GET /api/quota-alerts` → `alerts.check_quota_alerts(threshold, channels=["log"])` (dashboard load should NOT fire desktop/telegram — only surface visually + log; pass `channels=["log"]` so opening the page doesn't spam notifications)
- Returns the alert list as JSON
- Frontend: on load + SSE refresh, fetch `/api/quota-alerts`; if non-empty, populate the existing `#warningBanner` (index.html:38) with the alert messages

### Testing — `tests/test_alerts.py`

- `test_threshold_detection` — mock `agy_model_quota` returning a sub-threshold model → alert present
- `test_above_threshold_no_alert` — all models healthy → empty alerts
- `test_cooldown_dedup` — fire once, immediately re-run → second run reports `skipped_cooldown`, no duplicate
- `test_cooldown_expired` — manipulate state timestamp into the past → fires again
- `test_desktop_skip_when_absent` — mock `shutil.which`/`subprocess` raising → no crash, channel skipped
- `test_telegram_skip_when_unconfigured` — env unset → telegram not attempted
- `test_telegram_post` — env set, mock `urllib.request.urlopen` → POST attempted with correct URL/payload
- `test_log_channel_writes` — tmp ops.log → JSONL line appended

All external effects (subprocess, urllib, agy_model_quota) mocked. No real network/notifications.

### Server test — extend `tests/test_server.py`

- `test_api_quota_alerts` — mock `collectors.agy_model_quota`, GET `/api/quota-alerts` → 200 + `alerts` key

---

## Error Handling (cross-cutting)

- All collectors keep their existing `{..., "warning": str|None}` contract
- Alert channels swallow exceptions individually — one failing channel never blocks others
- `python3 -m dashboard.alerts check` exits 0 unconditionally
- Bash integration uses `|| true`

---

## Testing summary

| Phase | Tests |
|-------|-------|
| 1 CI | CI itself is the test; verify red-on-broken once |
| 2 split | existing 19 green (with patch-target edit) |
| 3 alerts | new `test_alerts.py` (8) + `test_server.py` extension (1) |

Both suites (`pytest tests -q`, `bash tests/run.sh`) must stay green.

---

## Out of scope (YAGNI)

- Background daemon / push polling (chose pull)
- Historical quota trend persistence (separate future feature)
- Alert acknowledgement / snooze UI
- Per-channel independent thresholds
