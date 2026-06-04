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
    job_event as _job_event_fn,
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
        pass

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
            _job_event_fn(
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


def invalidate_quota_cache():
    try:
        from dashboard.collectors.agy import agy_model_quota_cached
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
