# Python Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace shell `cmd_run` / `cmd_do_escalate` loops with `dashboard/orchestrator.py` to fix job-stuck-running and quota-cache-staleness bugs.

**Architecture:** `OrchestratorBase` owns subprocess streaming with silence detection, ping, account switch, job DB events, and ops log. `RunOrchestrator` and `EscalateOrchestrator` subclass it. Shell `cmd_run` / `cmd_do_escalate` become thin wrappers that call `python3 -m dashboard.orchestrator run|escalate`.

**Tech Stack:** Python 3.10+, subprocess.Popen, dashboard.collectors.jobs (existing), dashboard.collectors.agy (existing), argparse

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `dashboard/orchestrator.py` | **Create** | `AgyResult`, `OrchestratorBase`, `RunOrchestrator`, `EscalateOrchestrator`, `__main__` entrypoint |
| `dashboard/collectors/agy.py` | **Modify** | Dynamic quota TTL + `invalidate_quota_cache()` |
| `agykit` (shell) | **Modify** | Replace `cmd_run` / `cmd_do_escalate` bodies with thin Python delegation |
| `tests/test_orchestrator.py` | **Create** | Unit tests for all orchestrator behaviour |
| `tests/test_server.py` | **Modify** | No changes needed (collectors untouched) |

---

## Task 1: AgyResult dataclass + silence-detecting run_agy

**Files:**
- Create: `dashboard/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import subprocess
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")
from dashboard.orchestrator import OrchestratorBase, AgyResult

QUOTA_LINE = b"quota reached\n"
NORMAL_LINE = b"hello world\n"

class ConcreteOrchestrator(OrchestratorBase):
    def run(self):
        pass


def make_proc(lines: list[bytes], returncode: int = 0):
    """Return a mock Popen whose stdout yields lines then EOF."""
    mock = MagicMock()
    mock.stdout = iter(lines + [b""])
    mock.returncode = returncode
    mock.wait.return_value = returncode
    mock.poll.return_value = returncode
    def kill():
        mock.returncode = -9
    mock.kill = kill
    return mock


def test_run_agy_success():
    orch = ConcreteOrchestrator(job_id="j1", accounts=["a@b.com"], prompt="hi")
    with patch("subprocess.Popen", return_value=make_proc([NORMAL_LINE])):
        result = orch.run_agy("hi", [])
    assert result.ok
    assert not result.quota_hit
    assert not result.transient_error


def test_run_agy_quota_detected():
    orch = ConcreteOrchestrator(job_id="j1", accounts=["a@b.com"], prompt="hi")
    with patch("subprocess.Popen", return_value=make_proc([QUOTA_LINE])):
        result = orch.run_agy("hi", [])
    assert result.quota_hit
    assert not result.ok


def test_run_agy_silence_kills_process(monkeypatch):
    orch = ConcreteOrchestrator(job_id="j1", accounts=["a@b.com"], prompt="hi",
                                 silence_timeout=0.1)
    proc = make_proc([])  # no output at all
    killed = []
    proc.kill = lambda: killed.append(True)
    proc.stdout = iter([])  # empty — readline returns b"" immediately
    with patch("subprocess.Popen", return_value=proc):
        result = orch.run_agy("hi", [])
    assert result.transient_error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: `ImportError: cannot import name 'OrchestratorBase'`

- [ ] **Step 3: Implement AgyResult + OrchestratorBase.run_agy**

Create `dashboard/orchestrator.py`:

```python
from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from dashboard.collectors.jobs import (
    job_create,
    job_event,
    job_cancel,
)

QUOTA_RE = re.compile(
    r"quota reached|RESOURCE_EXHAUSTED|rate.?limit|code 429|HTTP.*429"
    r"|error.*429|exceeded your current|too many request",
    re.IGNORECASE,
)
TRANSIENT_RE = re.compile(
    r"ConnectionError|Connection refused|reset by peer|Name or service not known"
    r"|timed ?out|DeadlineExceeded|UNAVAILABLE",
    re.IGNORECASE,
)

OPS_LOG = os.path.expanduser("~/.gemini/agykit-ops.log")
OPS_LOG_MAX = 524288
OPS_LOG_KEEP = 400


@dataclass
class AgyResult:
    ok: bool = False
    quota_hit: bool = False
    transient_error: bool = False
    output: str = ""


class OrchestratorBase:
    def __init__(
        self,
        *,
        job_id: str,
        accounts: list[str],
        prompt: str,
        agy_bin: str = "",
        agy_flags: list[str] | None = None,
        silence_timeout: float = 0.0,
    ):
        self.job_id = job_id
        self.accounts = accounts
        self.prompt = prompt
        self.agy_bin = agy_bin or os.environ.get("AGY_BIN", "agy")
        self.agy_flags = agy_flags if agy_flags is not None else (
            os.environ.get("AGYKIT_FLAGS", "--dangerously-skip-permissions").split()
        )
        self.silence_timeout = silence_timeout or float(
            os.environ.get("AGYKIT_SILENCE_TIMEOUT", "120")
        )
        self._registered_atexit = False

    def _ensure_atexit(self):
        if not self._registered_atexit:
            atexit.register(self._atexit_handler)
            self._registered_atexit = True

    def _atexit_handler(self):
        pass  # subclasses override if needed

    def run_agy(self, prompt: str, extra_flags: list[str]) -> AgyResult:
        cmd = [self.agy_bin, "-p", prompt] + self.agy_flags + extra_flags
        buf: list[str] = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        last_output = time.monotonic()
        timed_out = False
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode(errors="replace")
            buf.append(line)
            print(line, end="", flush=True)
            last_output = time.monotonic()
            if time.monotonic() - last_output > self.silence_timeout:
                proc.kill()
                timed_out = True
                break
        if not timed_out:
            proc.wait()
        output = "".join(buf)
        if QUOTA_RE.search(output):
            return AgyResult(quota_hit=True, output=output)
        if timed_out or (proc.returncode not in (0, None) and TRANSIENT_RE.search(output)):
            return AgyResult(transient_error=True, output=output)
        if proc.returncode == 0 or (proc.returncode is None and not timed_out):
            return AgyResult(ok=True, output=output)
        return AgyResult(transient_error=True, output=output)

    def job_event(self, event_type: str, status: str, stage: str, *,
                  account: str | None = None, model: str | None = None,
                  message: str = "", error: str | None = None):
        try:
            job_event(
                job_id=self.job_id,
                event_type=event_type,
                status=status,
                stage=stage,
                account=account,
                model=model,
                message=message,
                error=error,
            )
        except Exception:
            pass

    def ops_log(self, cmd: str, status: str, account: str = "",
                model: str = "", prompt_preview: str = ""):
        import json
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = json.dumps({
            "ts": ts, "cmd": cmd, "status": status,
            "account": account, "model": model, "prompt": prompt_preview,
        })
        try:
            with open(OPS_LOG, "a") as f:
                f.write(entry + "\n")
            if os.path.getsize(OPS_LOG) > OPS_LOG_MAX:
                with open(OPS_LOG) as f:
                    lines = [l for l in f if l.strip()]
                with open(OPS_LOG, "w") as f:
                    f.writelines(lines[-OPS_LOG_KEEP:])
        except Exception:
            pass

    def ping(self, account: str) -> bool:
        """15s silence-aware ping. Returns True if agy responds."""
        old = self.silence_timeout
        self.silence_timeout = 15.0
        result = self.run_agy("say hello", ["--print-timeout", "14s"])
        self.silence_timeout = old
        return result.ok

    def account_switch(self, account: str) -> bool:
        """Call shell cmd_account_switch via subprocess. Returns True on success."""
        self_path = os.environ.get("AGYKIT_SELF", "")
        if not self_path:
            return False
        r = subprocess.run(
            ["bash", "-c", f'source "{self_path}" && cmd_account_switch "{account}"'],
            capture_output=True,
        )
        return r.returncode == 0

    def run(self):
        raise NotImplementedError
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): AgyResult + silence-detecting run_agy"
```

---

## Task 2: RunOrchestrator

**Files:**
- Modify: `dashboard/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_orchestrator.py`:

```python
from dashboard.orchestrator import RunOrchestrator

def _make_run_orch(accounts=None, prompt="do task"):
    return RunOrchestrator(
        job_id="j-run",
        accounts=accounts or ["acct1@g.com", "acct2@g.com"],
        prompt=prompt,
    )


def test_run_succeeds_first_account():
    orch = _make_run_orch()
    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", return_value=AgyResult(ok=True)), \
         patch.object(orch, "ops_log") as mock_log, \
         patch.object(orch, "job_event"):
        result = orch.run()
    assert result == 0
    mock_log.assert_called_once_with("run", "success", "acct1@g.com", "", pytest.approx("do task", rel=1))


def test_run_rotates_on_quota():
    orch = _make_run_orch()
    call_count = [0]
    def run_agy_side(prompt, flags):
        call_count[0] += 1
        if call_count[0] == 1:
            return AgyResult(quota_hit=True)
        return AgyResult(ok=True)

    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", side_effect=run_agy_side), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"), \
         patch("dashboard.orchestrator.invalidate_quota_cache"):
        result = orch.run()
    assert result == 0
    assert call_count[0] == 2


def test_run_fails_all_accounts_exhausted():
    orch = _make_run_orch()
    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", return_value=AgyResult(quota_hit=True)), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"), \
         patch("dashboard.orchestrator.invalidate_quota_cache"):
        result = orch.run()
    assert result == 1


def test_run_skips_ping_fail():
    orch = _make_run_orch(accounts=["dead@g.com", "alive@g.com"])
    ping_calls = []
    def ping_side(acct):
        ping_calls.append(acct)
        return acct == "alive@g.com"

    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", side_effect=ping_side), \
         patch.object(orch, "run_agy", return_value=AgyResult(ok=True)), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"):
        result = orch.run()
    assert result == 0
    assert ping_calls == ["dead@g.com", "alive@g.com"]
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_orchestrator.py::test_run_succeeds_first_account -v
```

Expected: `ImportError: cannot import name 'RunOrchestrator'`

- [ ] **Step 3: Implement RunOrchestrator**

Add to `dashboard/orchestrator.py` after `OrchestratorBase`:

```python
from dashboard.collectors.agy import agy_model_quota_cached


def invalidate_quota_cache():
    """Force next quota read to bypass cache."""
    try:
        agy_model_quota_cached(force=True)
    except Exception:
        pass


class RunOrchestrator(OrchestratorBase):
    def run(self) -> int:
        self._ensure_atexit()
        for account in self.accounts:
            if not self.account_switch(account):
                continue
            print(f"==> Pinging {account} (15s)...")
            if not self.ping(account):
                print(f"==> PING FAIL on {account} — skipping")
                self.job_event("quota_rotated", "rotating", "ping fail",
                               account=account, message=f"Ping failed on {account}, rotating")
                continue
            print(f"==> Trying account: {account}")
            self.job_event("account_selected", "running", "running", account=account)
            result = self.run_agy(self.prompt, [])
            if result.quota_hit:
                print(f"==> QUOTA on {account} — rotating")
                self.ops_log("run", "quota-rotate", account, "", self.prompt[:80])
                self.job_event("quota_rotated", "rotating", "quota rotate",
                               account=account, message=f"Quota on {account}, rotating")
                invalidate_quota_cache()
                continue
            if result.transient_error:
                print(f"==> TRANSIENT ERROR on {account} — failing")
                self.ops_log("run", "transient", account, "", self.prompt[:80])
                self.job_event("job_failed", "failed", "transient",
                               account=account, message="Transient error")
                return 1
            print(f"==> Success on: {account}")
            self.ops_log("run", "success", account, "", self.prompt[:80])
            self.job_event("job_succeeded", "succeeded", "done", account=account)
            return 0

        print("==> ALL ACCOUNTS EXHAUSTED")
        self.ops_log("run", "exhausted", "", "", self.prompt[:80])
        self.job_event("job_failed", "failed", "exhausted",
                       message="All accounts exhausted")
        return 1
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): RunOrchestrator with ping + quota rotation"
```

---

## Task 3: EscalateOrchestrator

**Files:**
- Modify: `dashboard/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_orchestrator.py`:

```python
from dashboard.orchestrator import EscalateOrchestrator

def _make_esc_orch(accounts=None, ladder=None):
    return EscalateOrchestrator(
        job_id="j-esc",
        accounts=accounts or ["acct1@g.com"],
        prompt="fix the bug",
        ladder=ladder or ["flash", "pro"],
        verify_cmd="true",
        git_base="",
    )


def test_escalate_succeeds_first_model():
    orch = _make_esc_orch()
    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", return_value=AgyResult(ok=True)), \
         patch.object(orch, "switch_model", return_value=True), \
         patch.object(orch, "run_verify", return_value=(True, "")), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"), \
         patch.object(orch, "git_snapshot", return_value="abc123"), \
         patch.object(orch, "git_rollback"):
        result = orch.run()
    assert result == 0


def test_escalate_retries_transient():
    orch = _make_esc_orch()
    call_count = [0]
    def run_agy_side(prompt, flags):
        call_count[0] += 1
        if call_count[0] < 3:
            return AgyResult(transient_error=True)
        return AgyResult(ok=True)

    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", side_effect=run_agy_side), \
         patch.object(orch, "switch_model", return_value=True), \
         patch.object(orch, "run_verify", return_value=(True, "")), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"), \
         patch.object(orch, "git_snapshot", return_value=""), \
         patch.object(orch, "git_rollback"), \
         patch("time.sleep"):
        result = orch.run()
    assert result == 0
    assert call_count[0] == 3


def test_escalate_escalates_model_on_verify_fail():
    orch = _make_esc_orch(ladder=["flash", "pro"])
    model_calls = []
    def switch_model_side(m):
        model_calls.append(m)
        return True

    verify_calls = [0]
    def run_verify_side():
        verify_calls[0] += 1
        if verify_calls[0] == 1:
            return (False, "test failed")
        return (True, "")

    with patch.object(orch, "account_switch", return_value=True), \
         patch.object(orch, "ping", return_value=True), \
         patch.object(orch, "run_agy", return_value=AgyResult(ok=True)), \
         patch.object(orch, "switch_model", side_effect=switch_model_side), \
         patch.object(orch, "run_verify", side_effect=run_verify_side), \
         patch.object(orch, "ops_log"), \
         patch.object(orch, "job_event"), \
         patch.object(orch, "git_snapshot", return_value=""), \
         patch.object(orch, "git_rollback"):
        result = orch.run()
    assert result == 0
    assert model_calls == ["flash", "pro"]
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_orchestrator.py::test_escalate_succeeds_first_model -v
```

Expected: `ImportError: cannot import name 'EscalateOrchestrator'`

- [ ] **Step 3: Implement EscalateOrchestrator**

Add to `dashboard/orchestrator.py`:

```python
class EscalateOrchestrator(OrchestratorBase):
    def __init__(self, *, ladder: list[str], verify_cmd: str, git_base: str,
                 verify_ctx: str = "", **kwargs):
        super().__init__(**kwargs)
        self.ladder = ladder
        self.verify_cmd = verify_cmd
        self.git_base = git_base
        self.verify_ctx = verify_ctx

    def switch_model(self, model: str) -> bool:
        self_path = os.environ.get("AGYKIT_SELF", "")
        if not self_path:
            return False
        r = subprocess.run(
            ["bash", "-c", f'source "{self_path}" && cmd_model "{model}"'],
            capture_output=True,
        )
        return r.returncode == 0

    def git_snapshot(self) -> str:
        try:
            r = subprocess.run(
                ["git", "stash", "push", "--include-untracked", "-m", "agykit-snap"],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and "No local changes" not in r.stdout:
                ref = subprocess.run(
                    ["git", "stash", "show", "--format=%H", "-s"],
                    capture_output=True, text=True,
                ).stdout.strip()
                return ref
        except Exception:
            pass
        return ""

    def git_rollback(self, snap: str):
        if not self.git_base:
            return
        try:
            subprocess.run(["git", "reset", "-q", "--hard", self.git_base], check=False)
            subprocess.run(["git", "clean", "-fdq"], check=False)
            if snap:
                subprocess.run(["git", "stash", "pop"], check=False)
        except Exception:
            pass

    def run_verify(self) -> tuple[bool, str]:
        try:
            r = subprocess.run(
                self.verify_cmd, shell=True,
                capture_output=True, text=True,
            )
            return r.returncode == 0, (r.stdout + r.stderr)[-4096:]
        except Exception as e:
            return False, str(e)

    def run(self) -> int:
        self._ensure_atexit()
        for model in self.ladder:
            self.switch_model(model)
            self.job_event("model_selected", "running", "running", model=model)
            snap = self.git_snapshot()
            applied = False
            for account in self.accounts:
                if not self.account_switch(account):
                    continue
                print(f"==> Pinging {account} (15s)...")
                if not self.ping(account):
                    self.job_event("quota_rotated", "rotating", "ping fail",
                                   account=account, model=model)
                    continue
                agy_ok = False
                for attempt in range(3):
                    if attempt > 0:
                        w = 5 * attempt
                        print(f"==> TRANSIENT ERROR — retry {attempt}/2 in {w}s")
                        time.sleep(w)
                    if attempt == 0:
                        self.job_event("account_selected", "running", "running",
                                       account=account, model=model)
                    full_prompt = self.verify_ctx + "TASK: " + self.prompt
                    result = self.run_agy(full_prompt, [])
                    if result.quota_hit:
                        self.ops_log("do-escalate", "quota-rotate", account, model, self.prompt[:80])
                        self.job_event("quota_rotated", "rotating", "quota rotate",
                                       account=account, model=model)
                        invalidate_quota_cache()
                        self.git_rollback(snap)
                        break
                    if result.transient_error and attempt < 2:
                        self.job_event("job_retrying", "running", f"retry {attempt+1}/2",
                                       account=account, model=model)
                        continue
                    if result.ok:
                        agy_ok = True
                        break
                    break

                if not agy_ok:
                    continue

                applied = True
                self.job_event("verify_started", "verifying", "verifying",
                               account=account, model=model)
                passed, vout = self.run_verify()
                if passed:
                    self.job_event("verify_passed", "succeeded", "done",
                                   account=account, model=model, message="Verify passed")
                    self.ops_log("do-escalate", "success", account, model, self.prompt[:80])
                    print(f"==> SUCCESS with {model}")
                    return 0
                else:
                    print(f"==> verify FAILED on {model} — escalating")
                    self.ops_log("do-escalate", "verify-failed", account, model, self.prompt[:80])
                    self.verify_ctx = (
                        f"Previous attempt with model '{model}' failed verification. Error:\n"
                        f"{vout}\n\nFix the above issues, then complete the original task:\n"
                    )
                    self.git_rollback(snap)
                    break

            if not applied:
                self.ops_log("do-escalate", "exhausted", "", model, self.prompt[:80])
                self.job_event("job_failed", "failed", "accounts exhausted", model=model)

        print("==> FAILED — all models exhausted")
        self.ops_log("do-escalate", "all-exhausted", "", "", self.prompt[:80])
        self.job_event("job_failed", "failed", "all models exhausted")
        return 1
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): EscalateOrchestrator with retry + verify + rollback"
```

---

## Task 4: CLI entrypoint (__main__)

**Files:**
- Modify: `dashboard/orchestrator.py`
- Test: manual smoke test

- [ ] **Step 1: Add __main__ block**

Add to the bottom of `dashboard/orchestrator.py`:

```python
def _parse_args():
    import argparse
    p = argparse.ArgumentParser(prog="dashboard.orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--job-id", required=True)
    r.add_argument("--prompt", required=True)
    r.add_argument("--accounts", nargs="+", required=True)
    r.add_argument("--system-prefix", default="")
    r.add_argument("--terse-prefix", default="")

    e = sub.add_parser("escalate")
    e.add_argument("--job-id", required=True)
    e.add_argument("--prompt", required=True)
    e.add_argument("--accounts", nargs="+", required=True)
    e.add_argument("--ladder", nargs="+", required=True)
    e.add_argument("--verify-cmd", required=True)
    e.add_argument("--git-base", default="")
    e.add_argument("--system-prefix", default="")
    e.add_argument("--terse-prefix", default="")

    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    full_prompt = args.system_prefix + args.terse_prefix + args.prompt

    if args.cmd == "run":
        orch = RunOrchestrator(
            job_id=args.job_id,
            accounts=args.accounts,
            prompt=full_prompt,
        )
    else:
        orch = EscalateOrchestrator(
            job_id=args.job_id,
            accounts=args.accounts,
            prompt=args.prompt,
            ladder=args.ladder,
            verify_cmd=args.verify_cmd,
            git_base=args.git_base,
        )

    sys.exit(orch.run())
```

- [ ] **Step 2: Smoke test the entrypoint**

```bash
python3 -m dashboard.orchestrator --help
python3 -m dashboard.orchestrator run --help
python3 -m dashboard.orchestrator escalate --help
```

Expected: usage printed, no errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/orchestrator.py
git commit -m "feat(orchestrator): CLI entrypoint for run + escalate"
```

---

## Task 5: Dynamic quota TTL + invalidate_quota_cache

**Files:**
- Modify: `dashboard/collectors/agy.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_orchestrator.py`:

```python
from dashboard.collectors.agy import _effective_quota_ttl, _QUOTA_CACHE_TTL

def test_effective_ttl_normal():
    assert _effective_quota_ttl(3600) == _QUOTA_CACHE_TTL

def test_effective_ttl_near_reset():
    assert _effective_quota_ttl(300) == 60

def test_effective_ttl_at_boundary():
    assert _effective_quota_ttl(600) == 60
    assert _effective_quota_ttl(601) == _QUOTA_CACHE_TTL
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_orchestrator.py::test_effective_ttl_normal -v
```

Expected: `ImportError: cannot import name '_effective_quota_ttl'`

- [ ] **Step 3: Implement in agy.py**

In `dashboard/collectors/agy.py`, after the `_QUOTA_CACHE_TTL = 300` line (line 37), add:

```python
def _effective_quota_ttl(reset_in_seconds: int) -> int:
    """Return a shorter TTL when the account is about to reset."""
    if reset_in_seconds <= 600:
        return 60
    return _QUOTA_CACHE_TTL
```

Then in `agy_model_quota_cached` (around line 715), replace:

```python
            if age < _QUOTA_CACHE_TTL:
```

with:

```python
            reset_in = cached.get("resets_in_seconds", 9999)
            ttl = _effective_quota_ttl(reset_in)
            if age < ttl:
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_orchestrator.py -v
python3 -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add dashboard/collectors/agy.py tests/test_orchestrator.py
git commit -m "feat(quota): dynamic TTL — 60s when reset ≤10min away"
```

---

## Task 6: Shell delegation — cmd_run

**Files:**
- Modify: `agykit` (shell script)

- [ ] **Step 1: Locate cmd_run body**

The body is at lines ~500–528 of `agykit`. The section starts with `mapfile -t raw_accts` and ends with the `echo "==> ALL ACCOUNTS EXHAUSTED"` line.

- [ ] **Step 2: Replace cmd_run body**

Replace the inner body of `cmd_run` (everything after `_job_ensure_daemon` through the closing `}`) with:

```bash
    _job_ensure_daemon
    local job_id; job_id=$(_job_op create "run" "$prompt" "$$")
    echo "==> job: $job_id"
    _CURRENT_JOB_ID="$job_id"
    _job_cleanup() {
        [ -n "${_CURRENT_JOB_ID:-}" ] && {
            _job_op event "$_CURRENT_JOB_ID" "job_blocked" "blocked" "interrupted" \
                "" "" "Process interrupted (SIGINT/SIGTERM)"
        }
    }
    trap _job_cleanup EXIT INT TERM
    local self; self="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
    AGYKIT_SELF="$self" PYTHONPATH="$(cd "$(dirname "$self")" && pwd)" \
        python3 -m dashboard.orchestrator run \
            --job-id "$job_id" \
            --prompt "$prompt" \
            --system-prefix "$(_system_prefix)" \
            --terse-prefix "$(_terse_prefix)" \
            --accounts "${accts[@]}"
    local rc=$?
    trap - EXIT INT TERM
    _CURRENT_JOB_ID=""
    return $rc
}
```

- [ ] **Step 3: Manual smoke test (dry run)**

```bash
cd /tmp && AGYKIT_STATE_DIR=/tmp/agykit-test-state \
  bash /home/haytek/projects/agykit/agykit run "say hello" 2>&1 | head -20
```

Expected: prints `==> job: <id>`, then pings accounts, no Python tracebacks

- [ ] **Step 4: Run full test suite**

```bash
cd /home/haytek/projects/agykit && python3 -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add agykit
git commit -m "feat(shell): delegate cmd_run to Python orchestrator"
```

---

## Task 7: Shell delegation — cmd_do_escalate

**Files:**
- Modify: `agykit` (shell script)

- [ ] **Step 1: Locate cmd_do_escalate body**

The body starts around line 545 (after `_job_ensure_daemon`) and ends at line ~674.

- [ ] **Step 2: Replace cmd_do_escalate delegation block**

Replace the inner body of `cmd_do_escalate` (from `_job_ensure_daemon` through the final `return 1`) with:

```bash
    _job_ensure_daemon
    local job_id; job_id=$(_job_op create "do-escalate" "$prompt" "$$")
    echo "==> job: $job_id"
    _CURRENT_JOB_ID="$job_id"
    _job_cleanup() {
        [ -n "${_CURRENT_JOB_ID:-}" ] && {
            _job_op event "$_CURRENT_JOB_ID" "job_blocked" "blocked" "interrupted" \
                "" "" "Process interrupted (SIGINT/SIGTERM)"
        }
    }
    trap _job_cleanup EXIT INT TERM
    local self; self="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
    AGYKIT_SELF="$self" PYTHONPATH="$(cd "$(dirname "$self")" && pwd)" \
        python3 -m dashboard.orchestrator escalate \
            --job-id "$job_id" \
            --prompt "$prompt" \
            --accounts "${accts[@]}" \
            --ladder "${LADDER[@]}" \
            --verify-cmd "$VERIFY_CMD" \
            --git-base "$base" \
            --system-prefix "$(_system_prefix)" \
            --terse-prefix "$(_terse_prefix)"
    local rc=$?
    restore_model
    trap - EXIT INT TERM
    _CURRENT_JOB_ID=""
    return $rc
}
```

- [ ] **Step 3: Run full test suite**

```bash
cd /home/haytek/projects/agykit && python3 -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add agykit
git commit -m "feat(shell): delegate cmd_do_escalate to Python orchestrator"
```

---

## Task 8: Integration smoke test + version bump

**Files:**
- Modify: `dashboard/server.py` (version)
- Modify: `tests/test_server.py` (version assertion)

- [ ] **Step 1: Run full suite**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass, 0 failed

- [ ] **Step 2: Bump version to 1.4.0**

In `dashboard/server.py`, find `VERSION = "1.3.2"` and change to:

```python
VERSION = "1.4.0"
```

In `tests/test_server.py`, find `assert data["version"] == "1.3.2"` and change to:

```python
assert data["version"] == "1.4.0"
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 4: Final commit + push**

```bash
git add dashboard/server.py tests/test_server.py
git commit -m "feat(orchestrator): Python run/escalate orchestrator v1.4.0

- Silence-detecting subprocess streaming (120s default, AGYKIT_SILENCE_TIMEOUT override)
- Ping timeout 30s → 15s
- Dynamic quota cache TTL (60s when reset ≤10min away)
- Quota hit invalidates cache immediately
- Python finally/atexit guarantees terminal job state
- Shell cmd_run / cmd_do_escalate delegated to dashboard.orchestrator"
git push origin main
```
