# agykit Live Job Observability Plan

## Goal

Make `agykit` jobs observable while they are running so the CLI and dashboard can show:

- the current execution stage
- the active account and model
- verify results
- quota rotation events
- rollback and final outcome
- elapsed time and latest error

The goal is to let a user follow a running `agykit run` or `agykit do-escalate`
job closely, without reading raw logs.

## Problem Statement

Today, `agykit` already logs successful and failed outcomes, but the process is
not easy to observe while it is active. A user cannot reliably answer questions
like:

- Which account is currently active?
- Which model is being used right now?
- Is the job waiting on verify, rotating accounts, or rolling back?
- What was the latest failure reason?
- Which job is still running if multiple jobs are in flight?

The CLI needs a structured job state model, and the dashboard should render the
same state.

## Design

Use one shared job model for both CLI and dashboard.

### Core Concepts

- `job_id`: unique identifier for one invocation
- `command`: `run` or `do-escalate`
- `status`: `queued`, `starting`, `running`, `verifying`, `rotating`,
  `rolling_back`, `succeeded`, `failed`, `blocked`
- `stage`: short human-readable phase label
- `account`: active email address, when available
- `model`: active model or effort label, when available
- `started_at`, `updated_at`, `ended_at`
- `last_error`
- `verify_result`
- `prompt`

### Storage

Split the storage into two layers:

- current snapshot
- append-only event log

Suggested paths:

- `~/.gemini/agykit-jobs/<job_id>.json`
- `~/.gemini/agykit-jobs/<job_id>.events.jsonl`

Keep `~/.gemini/agykit-ops.log` for backward compatibility with the existing
history view.

### Event Types

Emit a job event whenever a meaningful transition happens:

- `job_started`
- `account_selected`
- `model_selected`
- `prompt_dispatched`
- `quota_rotated`
- `verify_started`
- `verify_passed`
- `verify_failed`
- `rollback_started`
- `rollback_finished`
- `job_succeeded`
- `job_failed`
- `job_blocked`

Each event should carry:

- `job_id`
- `ts`
- `status`
- `stage`
- `account`
- `model`
- `message`
- optional `error`

## Implementation Plan

### 1. Job State Core

File targets:

- `agykit`
- `dashboard/collectors/jobs.py` or `dashboard/jobs.py`

Work:

- add a small job-state helper layer
- generate `job_id`
- create/update snapshot files
- append structured events
- expose simple read helpers for CLI and dashboard

### 2. Instrument `run`

File target:

- `agykit`

Work:

- create a job record at the start
- write events when account selection begins
- write events when the selected account changes
- mark prompt dispatch and completion
- update the snapshot on success, quota rotation, or failure

### 3. Instrument `do-escalate`

File target:

- `agykit`

Work:

- add events for each model-ladder step
- record verify start and verify result
- record rollback start and finish
- preserve the final failure reason if all models fail

### 4. CLI Observability Commands

File target:

- `agykit`

Add commands or submodes such as:

- `agykit jobs`
- `agykit watch <job_id>`
- `agykit log <job_id>`
- `agykit status`

Behavior:

- `jobs` shows active and recent jobs
- `watch` shows a compact live stream for one job
- `log` shows the event history for one job
- `status` shows the latest active job summary

### 5. Dashboard Integration

File targets:

- `dashboard/server.py`
- `web/index.html`
- `web/app.js`
- `web/style.css`

Work:

- add API endpoints for job state and job events
- render an "Active Job" card
- show stage, status, model, account, elapsed time, and last error
- refresh the card alongside the existing SSE refresh flow
- keep the card visually separate from the activity feed

### 6. Shared Collector Exports

File target:

- `dashboard/collectors/__init__.py`

Work:

- export the new job helpers so both CLI and dashboard can use the same read
  logic

### 7. Tests

File targets:

- `tests/test_collectors.py`
- `tests/test_server.py`
- `tests/test_do_escalate.sh`
- `tests/test_git_safety.sh`

Test cases:

- job snapshot creation
- event ordering
- quota rotation reporting
- verify failure reporting
- rollback reporting
- active job API response
- watch/log output shape

### 8. Documentation

File targets:

- `README.md`
- `docs/plans/2026-06-01-agykit-live-job-observability-plan.md`

Work:

- document the new CLI commands
- describe the job lifecycle
- show an example watch output

## Suggested Sequence

1. Add the job state and event model.
2. Wire `run` and `do-escalate` into the model.
3. Add CLI read commands.
4. Add the dashboard API and card.
5. Add tests.
6. Update docs.

## Acceptance Criteria

The feature is done when:

- a running `agykit` job can be identified by `job_id`
- the current stage is visible from the CLI
- the dashboard can render the active job state
- quota rotation and verify failures are visible as events
- rollback and final outcomes are recorded
- tests cover the main job paths

