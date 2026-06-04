# Python Orchestrator Design

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** Replace shell `cmd_run` / `cmd_do_escalate` loops with `dashboard/orchestrator.py`

---

## Problem

Two stability issues motivate this rewrite:

1. **Job stuck in "running"** — `agy` enters a silent phase (no output) but its PID stays alive. The current stale recovery only fires after 300s of DB silence AND owner process death. A silent-but-live PID can block the system for the full 15m job timeout.

2. **Quota cache staleness** — `_QUOTA_CACHE_TTL = 300s` is fixed regardless of when the account resets. Near a reset boundary, the cache can report "available" when the account is actually exhausted, causing a job to start on a bad account and waste a rotation cycle.

---

## Architecture

```
agykit (shell)
  └── cmd_run / cmd_do_escalate
        └── python3 -m dashboard.orchestrator run|escalate [args]
              ├── OrchestratorBase          # shared: job DB, ping, account switch, ops_log
              ├── RunOrchestrator           # run loop
              └── EscalateOrchestrator      # model ladder + verify + rollback
```

Shell retains:
- `cmd_account_switch email` — writes agy accounts config
- `cmd_model model` — writes agy model config
- Env var sourcing (`AGY_BIN`, `AGY_FLAGS`, `TIMEOUT`, `AGYKIT_SILENCE_TIMEOUT`)
- `agykit run "..."` entrypoint — thin shell function calling `python3 -m dashboard.orchestrator`

---

## Components

### OrchestratorBase

Shared by both orchestrators. Owns:

- **`run_agy(prompt, flags) → AgyResult`** — core improvement. Streams subprocess stdout line-by-line, tracks last output timestamp. If `time.monotonic() - last_output > SILENCE_TIMEOUT` (default 120s, env override `AGYKIT_SILENCE_TIMEOUT`), kills the process and returns `transient_error=True`. Also detects quota hits inline. PID liveness is irrelevant — silence alone triggers recovery.

```python
proc = subprocess.Popen([AGY_BIN, "-p", prompt, ...], stdout=PIPE, stderr=STDOUT)
last_output = time.monotonic()
for line in iter(proc.stdout.readline, b""):
    print(line.decode(), end="", flush=True)
    last_output = time.monotonic()
    if time.monotonic() - last_output > SILENCE_TIMEOUT:
        proc.kill()
        return AgyResult(transient_error=True)
```

- **`ping(account) → bool`** — 15s timeout (down from 30s), uses same silence detection as `run_agy`. Skips accounts that don't respond within the window.

- **`account_switch(email)`** — subprocess call to shell `cmd_account_switch`.

- **`ops_log(cmd, status, account, model, prompt)`** — writes to existing ops log format.

- **`detect_quota(text) → bool`** — applies `QUOTA_RE` regex.

- **`job_event(event, status, stage, ...)`** — writes directly to job DB (no socket indirection needed; orchestrator runs in same process context as the job).

- **`finally` + `atexit` guarantee** — job always reaches a terminal DB state (`failed`, `succeeded`, `blocked`) even on unexpected exit. Replaces shell `trap _job_cleanup EXIT INT TERM`.

### RunOrchestrator

```
accounts = sorted_by_quota()
for account in accounts:
    switch(account)
    if not ping(account): job_event(quota_rotated), continue
    job_event(account_selected, running)
    result = run_agy(prompt)
    if result.quota_hit:
        ops_log(quota-rotate), job_event(quota_rotated), invalidate_quota_cache(), continue
    if result.transient_error:
        job_event(job_failed), exit 1   # run has no retry; escalate does
    if result.ok:
        ops_log(success), job_event(job_succeeded), exit 0
ops_log(exhausted), job_event(job_failed), exit 1
```

### EscalateOrchestrator

```
for model in LADDER:
    switch_model(model)
    snapshot = git_snapshot()
    for account in accounts:
        switch(account)
        if not ping(account): job_event(quota_rotated), continue
        for attempt in range(3):
            result = run_agy(prompt + verify_ctx)
            if result.quota_hit:
                rollback(snapshot), job_event(quota_rotated), break → next account
            if result.transient_error and attempt < 2:
                job_event(job_retrying), sleep(5 * attempt), continue
            if result.ok: break
        if not result.ok: continue → next account
        verify_result = run_verify_cmd()
        if passed:
            capture_diff(), job_event(verify_passed), ops_log(success), exit 0
        else:
            verify_ctx = build_error_ctx(verify_output)
            rollback(snapshot), job_event(verify_failed), escalate model
ops_log(all-exhausted), job_event(job_failed), exit 1
```

---

## Quota Cache Improvement

`agy_model_quota_cached()` in `dashboard/collectors/agy.py` gets a dynamic TTL:

```python
def _effective_ttl(reset_in_seconds: int) -> int:
    if reset_in_seconds <= 600:   # ≤10 min to reset
        return 60
    return _QUOTA_CACHE_TTL       # 300s default
```

Additionally, when `run_agy()` detects a quota hit it calls `invalidate_quota_cache()` to force a fresh read on the next dashboard poll — prevents the dashboard showing "Müsait" while the account is actually exhausted.

---

## Shell Entrypoint Change

```bash
# Before:
"$AGY_BIN" -p "$(_system_prefix)$(_terse_prefix)$prompt" $AGY_FLAGS \
  --print-timeout "$TIMEOUT" 2>&1 | tee /tmp/agykit-out.log
grep -qiE "$QUOTA_RE" /tmp/agykit-out.log && { ... rotate ... }

# After:
python3 -m dashboard.orchestrator run \
  --job-id "$job_id" \
  --prompt "$prompt" \
  --system-prefix "$(_system_prefix)" \
  --terse-prefix "$(_terse_prefix)" \
  --accounts "${accts[@]}"
# stdout streams to terminal; exit code propagates to shell
```

`do-escalate` similarly delegates to `dashboard.orchestrator escalate` with `--ladder`, `--verify-cmd`, `--git-base`.

---

## Error Handling

| Scenario | Before | After |
|---|---|---|
| `agy` silent (PID alive) | 300s stale sweep | 120s silence → `proc.kill()` → rotate |
| `agy` crashes (exit ≠ 0) | grep output only | returncode + output evaluated together |
| Ping hangs | 30s hard timeout | 15s + silence detection |
| Quota cache stale near reset | 5min TTL fixed | TTL=60s when reset ≤10min away |
| Shell trap missed | job stays "running" | Python `finally`/`atexit` → always terminal |
| DB lock contention | `busy_timeout=5000` | unchanged |

---

## Testing

- **`tests/test_orchestrator.py`** (new) — unit tests with mock subprocess:
  - Silence timeout triggers kill and transient_error
  - Quota regex detection in streaming output
  - Retry backoff (transient errors, 3 attempts)
  - `finally` block sets job to failed on unexpected exit
  - Dynamic quota TTL logic

- **`tests/test_collectors.py`** — no changes; collectors are untouched

- **`tests/test_cli_commands.sh`** — `agykit run` entrypoint still exits 0/1 correctly

---

## Out of Scope

- Dashboard SSE reconnect (separate issue)
- Test suite hardcoded version strings (fixed separately)
- `agykit switch`, `agykit model` commands (stay in shell)
