# agykit Dashboard API

This document summarizes the JSON endpoints used by the dashboard. All
responses are local-only and stdlib-backed.

## Common Response Shape

Successful responses are top-level JSON objects with shared metadata and
endpoint-specific payload fields:

```json
{
  "ok": true,
  "warning": null,
  "generated_at": "2026-06-03T15:20:00+03:00",
  "source": "agykit",
  "stale": false
}
```

Error responses follow this shape:

```json
{
  "ok": false,
  "error": {
    "code": "HEALTH_CHECK_FAILED",
    "message": "Could not inspect project configuration.",
    "fix": "Run agykit doctor from the project directory."
  },
  "generated_at": "2026-06-03T15:20:00+03:00"
}
```

## Endpoints

### `GET /api/health`

Returns local environment and project checks.

Useful fields:

- `overall_status`: `ok`, `warning`, or `critical`
- `summary`: passed, warning, and critical counts
- `checks[]`: dependency, storage, project, and agent data checks

Optional query parameters:

- `scope=system`
- `scope=project`
- `scope=agents`
- `fixable=true`

### `GET /api/active-job/timeline`

Returns the active job timeline, or the most recent job if no job is active.

Useful fields:

- `job_id`
- `snapshot`
- `timeline[]`
- `metrics`

### `GET /api/jobs/<job_id>/timeline`

Returns the timeline for a specific job id.

Optional query parameters:

- `include_raw=true`
- `limit=100`

### `GET /api/recommendation`

Returns the next recommended account and model pair.

Useful fields:

- `mode`: recommendation mode such as `balanced` or `reliability`
- `recommendation`: top account/model pair with confidence and reasons
- `alternatives[]`: fallback choices
- `rejected[]`: lower-priority options and reasons
- `signals`: scoring weights used by the collector

Optional query parameters:

- `mode=balanced`
- `mode=reliability`
- `mode=speed`
- `mode=cost_saving`
- `mode=aggressive`

### `GET /api/quota-forecast`

Returns quota burn-rate estimates and risk levels.

Useful fields:

- `overall_risk`
- `accounts[]`
- `accounts[].models[]`
- `recommendations[]`

Optional query parameters:

- `window=6h`
- `window=24h`
- `window=7d`
- `strategy=hybrid`

### `GET /api/agent-matrix`

Returns a normalized cross-agent performance comparison.

Useful fields:

- `range`
- `agents[]`
- `summary`

Optional query parameters:

- `range=24h`
- `range=7d`
- `range=30d`
- `include_models=true`
- `project=/path/to/project`

## Notes

- Missing data should degrade to `unknown`, not fail the UI.
- The dashboard refreshes only the cards affected by a source change.
- The server binds to `127.0.0.1` only.
- Fixture examples live in `tests/fixtures/dashboard/` and are used by the
  collector smoke tests.
