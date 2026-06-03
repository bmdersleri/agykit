# agykit Dashboard Enhancement Task List

**Date:** 2026-06-03  
**Status:** Draft  
**Scope:** Turn the dashboard enhancement proposal into an executable implementation checklist.

This document breaks the dashboard enhancement plan into a concrete sequence of tasks that can be executed incrementally. Each task is designed to be independently testable and to preserve backward compatibility with the current dashboard.

---

## Execution Principles

- Keep the implementation `stdlib-only` on the backend.
- Preserve existing dashboard behavior while adding new endpoints and cards.
- Prefer graceful degradation when data is missing, stale, or incomplete.
- Expose recommendations and warnings with explicit reasoning.
- Add tests before or alongside each feature, not after the full rollout.

---

## Phase 0: Current-State Audit

- [ ] Inspect `dashboard/server.py` to map current routes, SSE behavior, and response shapes.
- [ ] Inspect `dashboard/collectors/` to identify existing collectors, shared helpers, and file paths.
- [ ] Inspect `web/index.html`, `web/app.js`, and `web/style.css` to understand the current dashboard layout and update flow.
- [ ] Record the current job, quota, and agent data sources used by the dashboard.
- [ ] Identify any existing tests that must continue to pass unchanged.

## Phase 1: API Foundation

- [ ] Add a consistent JSON response envelope for new dashboard endpoints.
- [ ] Implement `GET /api/health` with structured checks and severity levels.
- [ ] Implement `GET /api/active-job/timeline` and `GET /api/jobs/<job_id>/timeline`.
- [ ] Implement `GET /api/recommendation` for account and model selection guidance.
- [ ] Implement `GET /api/quota-forecast` for burn-rate and exhaustion estimates.
- [ ] Implement `GET /api/agent-matrix` for cross-agent comparison metrics.
- [ ] Ensure every endpoint returns useful fallback data when inputs are missing.
- [ ] Standardize error responses so a single collector failure does not break the whole dashboard.

## Phase 2: Health Center

- [ ] Add backend health checks for required tools, writable directories, project config, and cache freshness.
- [ ] Include fix suggestions for missing dependencies and misconfigured project settings.
- [ ] Expose overall status, per-check status, and a last-scan timestamp.
- [ ] Render a Health Center card in the dashboard UI.
- [ ] Add compact and expanded display modes for the health card.
- [ ] Add severity-based filtering and a copy-fix-command action.
- [ ] Add tests for healthy, warning, critical, and stale health states.

## Phase 3: Job Timeline

- [ ] Build a timeline transformation layer from the existing job snapshot and event log format.
- [ ] Normalize job lifecycle events into a stable timeline structure.
- [ ] Add active-job detection with a fallback to the most recent completed job.
- [ ] Render timeline stages, timestamps, account, model, and current stage in the UI.
- [ ] Highlight failed, skipped, pending, and active events clearly.
- [ ] Provide access to raw event details in a developer-oriented view.
- [ ] Add tests for complete timelines, partial timelines, and missing event logs.

## Phase 4: Recommended Account/Model

- [ ] Define a transparent scoring model using quota, reliability, speed, freshness, and project fit.
- [ ] Support recommendation modes such as balanced, cost-saving, speed, reliability, and aggressive.
- [ ] Generate a primary recommendation, alternatives, rejected options, and a confidence score.
- [ ] Include the reasons and warnings that influenced the recommendation.
- [ ] Add a copy-command helper that produces the suggested CLI action.
- [ ] Render the recommendation card with risk badges and explanation text.
- [ ] Add tests for healthy quota, exhausted quota, low-reliability models, and missing history.

## Phase 5: Quota Forecast

- [ ] Implement a simple burn-rate forecast as the first supported method.
- [ ] Add optional job-based and hybrid forecast modes if enough data exists.
- [ ] Calculate per-account and per-model risk levels with confidence labels.
- [ ] Show estimated hours remaining, estimated jobs remaining, and reset information when available.
- [ ] Handle missing quota snapshots, sparse history, and inconsistent consumption data without failing the UI.
- [ ] Render a quota forecast card with actionable recommendations.
- [ ] Add tests for fresh data, stale data, no history, and sparse history.

## Phase 6: Agent Performance Matrix

- [ ] Normalize metrics across agy, Codex, Claude Code, and OpenCode data sources.
- [ ] Track jobs, success rate, token usage, average duration, verify failures, and rollback counts.
- [ ] Add model mix and escalation metrics where the source data supports them.
- [ ] Surface unknown values explicitly instead of substituting zero when data is unavailable.
- [ ] Render a sortable agent matrix with range filters and metric filters.
- [ ] Add short derived insights that explain the strongest and weakest performers.
- [ ] Add tests for partial data, missing Codex data, and missing Claude data.

## Phase 7: Live Updates

- [ ] Extend SSE event types so only the affected cards refresh when source data changes.
- [ ] Map source changes to dashboard updates for quota, job, recommendation, forecast, and agent-matrix data.
- [ ] Add stale-data indicators and per-card update timestamps.
- [ ] Keep the existing dashboard usable if SSE disconnects or a single refresh fails.
- [ ] Verify that live updates do not duplicate content or reset unrelated cards.

## Phase 8: Tests and Documentation

- [ ] Add backend unit tests for each new collector and endpoint.
- [ ] Create or expand fixtures for quota, job events, Claude history, and agent-specific data.
- [ ] Add smoke tests for the dashboard server and the new UI cards.
- [ ] Add tests for graceful degradation when files, caches, or history data are missing.
- [ ] Update the README with the new dashboard capabilities and usage notes.
- [ ] Add a dashboard API reference document if the endpoint surface becomes stable.

---

## Recommended Delivery Order

1. Audit the current implementation.
2. Add the API foundation and shared response shape.
3. Implement Health Center and Job Timeline first.
4. Add Recommendation and Quota Forecast next.
5. Implement the Agent Performance Matrix.
6. Wire SSE refreshes for the new cards.
7. Finish with tests, fixtures, and documentation.

---

## Definition Of Done

- The dashboard exposes the five new feature areas through stable API endpoints.
- Each new card renders useful information even when some inputs are missing.
- Recommendations explain why a choice was made.
- Forecasts and timelines are derived from existing local data sources.
- The full test suite passes after the changes.
