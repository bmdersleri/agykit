# Design: Claude Code Context Widgets

**Date:** 2026-05-31  
**Status:** Approved  
**Scope:** Two new info-cards in the agykit dashboard

---

## Overview

Add two widgets to the existing `info-section` 2×2 grid:
1. **RTK Tasarruf** — RTK token savings analytics
2. **CC Aktivitesi** — Claude Code activity stream from history + stats-cache

---

## Architecture

### Data Sources

| Source | Widget | Real-time? | Notes |
|--------|--------|-----------|-------|
| `rtk gain` subprocess | RTK Tasarruf | ~60s cache | No data file; must subprocess |
| `~/.claude/history.jsonl` | CC Aktivitesi | Yes | Updated each prompt |
| `~/.claude/stats-cache.json` | CC Aktivitesi | No (~1-2d lag) | CC computes periodically |

### New Collectors (`dashboard/collectors.py`)

#### `rtk_stats()`
- Calls `subprocess.run(['rtk', 'gain'], capture_output=True, text=True, timeout=5)`
- Parses stdout with regex:
  - `Total commands`, `Tokens saved`, efficiency % from the meter line
  - Top-10 command table rows: rank, cmd, count, saved, avg%
- In-process cache: 60s TTL (`_rtk_cache`, `_rtk_cache_ttl = 60`)
- Returns:
  ```json
  {
    "total_commands": 20154,
    "tokens_saved": 3500000,
    "efficiency_pct": 52.6,
    "top_commands": [
      {"rank": 1, "cmd": "rtk read", "count": 873, "saved": 2100000, "avg_pct": 30.9}
    ],
    "cached_at": 1234567890,
    "warning": null
  }
  ```
- On subprocess failure or timeout: returns `{"warning": "<error>", "tokens_saved": 0, ...}`

#### `cc_activity(limit=20)`
- Reads `~/.claude/history.jsonl` (last `limit` non-empty lines, tail from end)
- Reads `~/.claude/stats-cache.json` for `dailyActivity` — finds today and yesterday by date string
- Returns:
  ```json
  {
    "recent_prompts": [
      {
        "display": "/start",
        "timestamp": 1780231742312,
        "project": "agykit",
        "session_id": "25e0031b-..."
      }
    ],
    "latest_stats": {"date": "2026-05-29", "messages": 16425, "sessions": 93, "tool_calls": 2644, "available": true},
    "warning": null
  }
  ```
- `project` field = `os.path.basename(project_path)` from history entry
- Stats lookup: find the **most recent available date** in `dailyActivity` (not hardcoded today/yesterday). Return it as `latest_stats: {date, messages, sessions, tool_calls, available: true}`. If cache missing or empty: `available: false`.
- If history.jsonl missing: `recent_prompts: []`

### New Endpoints (`dashboard/server.py`)

```
GET /api/rtk-stats           → rtk_stats()
GET /api/cc-activity?limit=N → cc_activity(limit=N)
```

Both follow existing pattern: `json.dumps(result).encode()` with `Content-Type: application/json`.

---

## Frontend

### HTML (`web/index.html`)

Add two `<div class="info-card">` blocks inside `.info-section`:

```html
<div class="info-card" id="rtkStatsCard">
  <div class="info-card-title-group">
    <h3 class="info-card-title">RTK Tasarruf</h3>
  </div>
  <div id="rtkStatsBody" class="rtk-stats-body">Yükleniyor…</div>
</div>

<div class="info-card" id="ccActivityCard">
  <div class="info-card-title-group">
    <h3 class="info-card-title">CC Aktivitesi</h3>
  </div>
  <div id="ccActivityBody" class="cc-activity-body">Yükleniyor…</div>
</div>
```

### JavaScript (`web/app.js`)

#### `loadRtkStats()`
- `fetch('/api/rtk-stats')` → render:
  - Big number: `tokens_saved` formatted (e.g. "3.5M")
  - Efficiency bar: `<div class="eff-bar" style="width: X%">` + label
  - Top 3 commands table: cmd name (truncated 20 chars), count, avg%
- Called in `init()` + `setInterval(loadRtkStats, 60_000)`

#### `loadCcActivity()`
- `fetch('/api/cc-activity')` → render:
  - Stat chips row: `latest_stats.date` label + messages + tool_calls (shows actual date so user knows freshness)
  - Prompt list: last 10 entries, newest first
    - Each row: `[time-ago] [project-chip] [display text truncated 60 chars]`
  - `time-ago`: if <60s → "az önce", <60m → "Xdk", <24h → "Xsa", else date
- Called in `init()` + wired to SSE `heavy_refresh` event (same pattern as `loadOpsLog`)

### CSS (`web/style.css`)

New classes:
- `.rtk-stats-body` — flex column layout
- `.rtk-big-number` — large token count display
- `.eff-bar-track` / `.eff-bar` — efficiency progress bar
- `.rtk-cmd-table` — compact 3-column table (cmd, count, avg%)
- `.cc-activity-body` — flex column
- `.cc-stat-chips` — flex row of stat chips
- `.cc-stat-chip` — individual stat (label + value)
- `.cc-prompt-row` — single history entry row
- `.cc-project-chip` — colored project name badge

---

## Error Handling

- `rtk gain` timeout (5s) → show warning banner in card, `tokens_saved: 0`
- `history.jsonl` missing → empty prompt list, no error (normal on fresh install)
- `stats-cache.json` missing → `available: false` on both today/yesterday stats
- Both cards show existing `cq-unavail` style message on empty/error state

---

## Testing

Existing test suite (`python3 -m pytest tests -q`) must stay green.

New unit tests in `tests/test_collectors.py`:
- `test_rtk_stats_subprocess_failure` — mock subprocess failure, verify warning returned
- `test_cc_activity_no_history` — missing history.jsonl → empty prompts
- `test_cc_activity_no_stats_cache` — missing stats-cache.json → available: false
- `test_cc_activity_parse` — valid history.jsonl → correct project extraction

No new bash tests required (collectors only).

---

## Constraints

- Stdlib only: `subprocess`, `os`, `json`, `re`, `datetime` — no pip deps
- Read-only access to `~/.claude/` (no writes)
- `127.0.0.1` binding unchanged (dashboard/server.py untouched for network config)
