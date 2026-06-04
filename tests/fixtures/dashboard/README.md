# Dashboard Fixture Bundle

This directory contains small, deterministic dashboard fixtures used by the
collector and dashboard smoke tests.

Files:

- `project/.agykit.conf` and `project/.gitignore` for project health checks
- `project/CLAUDE_AGY_SYSTEM.md` for project configuration checks
- `quota-cache.json` for quota freshness and recommendation tests
- `statusline-latest.json` for statusline-related checks
- `jobs/example-job.json` and `jobs/example-job.events.jsonl` for timeline tests

The files are intentionally tiny so they can be copied into temporary test
directories without extra setup.
