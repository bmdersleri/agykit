import datetime as _dt
import importlib.util
import json
import os
import re
import shutil
import stat
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .agy import (
    agy_active_account,
    agy_model_quota,
    agy_model_quota_cached,
    agy_quota_status,
    agy_statusline_snapshot,
)
from .claude import claude_quota, claude_series
from .codex import codex_status, codex_usage
from .jobs import job_events, job_list, job_snapshot, job_stats
from ..state import resolve_job_state


_ACTIVE_JOB_STATUSES = {
    "starting",
    "running",
    "verifying",
    "rotating",
    "rolling_back",
}

_SYSTEM_DEPENDENCIES = {
    "agy": {"label": "agy", "fix": None},
    "python3": {"label": "Python", "fix": None},
    "git": {"label": "git", "fix": None},
    "tmux": {"label": "tmux", "fix": "sudo apt install tmux"},
    "jq": {"label": "jq", "fix": "sudo apt install jq"},
}
_CACHE_STALE_SECONDS = 300


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat()


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _safe_access(path: str, mode: int) -> bool:
    try:
        return os.access(path, mode)
    except Exception:
        return False


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _which(cmd: str) -> str | None:
    try:
        return shutil.which(cmd)
    except Exception:
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _parse_shell_assignments(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    if not os.path.isfile(path):
        return data
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def _severity_for_status(status: str) -> str:
    if status == "critical":
        return "high"
    if status in {"warning", "stale", "missing"}:
        return "medium"
    if status == "unknown":
        return "low"
    return "low"


def _make_check(
    *,
    check_id: str,
    label: str,
    category: str,
    status: str,
    message: str,
    details: str = "",
    fix: dict | None = None,
) -> dict:
    return {
        "id": check_id,
        "label": label,
        "category": category,
        "status": status,
        "severity": _severity_for_status(status),
        "message": message,
        "details": details,
        "fix": fix,
    }


def _cache_age_seconds(path: str) -> int | None:
    try:
        return max(0, int(_dt.datetime.now(_dt.timezone.utc).timestamp() - os.path.getmtime(path)))
    except Exception:
        return None


def _format_age_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _project_paths(project_dir: str) -> dict[str, str]:
    root = os.path.abspath(project_dir)
    return {
        "root": root,
        "config": os.path.join(root, ".agykit.conf"),
        "gitignore": os.path.join(root, ".gitignore"),
        "system_claude": os.path.join(root, "CLAUDE_AGY_SYSTEM.md"),
        "system_codex": os.path.join(root, "CODEX_AGY_SYSTEM.md"),
        "system_opencode": os.path.join(root, "OPENCODE_AGY_SYSTEM.md"),
        "dashboard_dir": os.path.join(root, "dashboard"),
        "web_dir": os.path.join(root, "web"),
    }


def health_status(
    project_dir: str | None = None,
    *,
    scope: str = "all",
    fixable: bool = False,
) -> dict:
    project_root = os.path.abspath(project_dir or os.getcwd())
    paths = _project_paths(project_root)
    cfg = _parse_shell_assignments(paths["config"])
    state = resolve_job_state()

    checks: list[dict] = []

    # System tools.
    for cmd, meta in _SYSTEM_DEPENDENCIES.items():
        found = _which(cmd)
        status = "ok" if found else "warning"
        message = f"Found in PATH: {found}" if found else f"{meta['label']} is missing or not executable."
        details = (
            f"{meta['label']} is required for dashboard and agykit workflows."
            if not found
            else f"{meta['label']} is available."
        )
        fix = None
        if meta["fix"]:
            fix = {
                "type": "command",
                "command": meta["fix"],
                "safe_to_run": False,
            }
        checks.append(
            _make_check(
                check_id=f"dependency.{cmd}",
                label=meta["label"],
                category="dependency",
                status=status,
                message=message,
                details=details,
                fix=fix,
            )
        )

    keyring_ok = _has_module("keyring")
    checks.append(
        _make_check(
            check_id="dependency.keyring",
            label="keyring",
            category="dependency",
            status="ok" if keyring_ok else "warning",
            message="Python keyring module available." if keyring_ok else "keyring is missing; snapshot and avatar refreshes may be degraded.",
            details="Used to read OAuth-backed account snapshots.",
            fix={
                "type": "command",
                "command": "python3 -m pip install keyring",
                "safe_to_run": False,
            }
            if not keyring_ok
            else None,
        )
    )

    # Storage and file-system checks.
    home_gemini = os.path.expanduser("~/.gemini")
    home_accounts = os.path.expanduser("~/.gemini/accounts")
    quota_cache = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")
    statusline = os.path.expanduser("~/.gemini/antigravity-cli/statusline-latest.json")
    claude_stats = os.path.expanduser("~/.claude/stats-cache.json")
    codex_home = os.path.expanduser("~/.codex")
    job_db = state["db_path"]
    job_dir = state["state_dir"]
    storage_targets = [
        ("storage.gemini", "~/.gemini", home_gemini, "base directory for agy state", "dir"),
        ("storage.accounts", "~/.gemini/accounts", home_accounts, "saved agy account snapshots", "dir"),
        ("storage.jobs", "job store", job_db, "agykit job database", "file"),
        ("storage.quota_cache", "quota cache", quota_cache, "cached agy model quota snapshot", "file"),
        ("storage.statusline", "statusline snapshot", statusline, "current agy statusline snapshot", "file"),
        ("storage.claude_stats", "Claude stats cache", claude_stats, "Claude Code activity cache", "file"),
        ("storage.codex_home", "Codex home", codex_home, "Codex local data", "dir"),
    ]

    for check_id, label, path, detail, kind in storage_targets:
        if kind == "dir":
            if os.path.isdir(path):
                status = "ok"
                message = "Writable" if _safe_access(path, os.W_OK) else "Readable only"
                age_seconds = None
            else:
                parent = os.path.dirname(path)
                can_write = _safe_access(parent or ".", os.W_OK)
                status = "ok" if can_write else "warning"
                message = "Directory can be created" if can_write else "Not writable"
                age_seconds = None
        else:
            if os.path.isfile(path):
                age_seconds = _cache_age_seconds(path)
                if age_seconds is not None and age_seconds > _CACHE_STALE_SECONDS:
                    status = "stale"
                    message = f"Cached data is {_format_age_seconds(age_seconds)} old."
                else:
                    status = "ok"
                    message = "Readable" if _safe_access(path, os.R_OK) else "Not readable"
            else:
                parent = os.path.dirname(path)
                can_write = _safe_access(parent or ".", os.W_OK)
                status = "warning" if can_write else "warning"
                message = "Missing file"
                age_seconds = None
        checks.append(
            _make_check(
                check_id=check_id,
                label=label,
                category="storage",
                status=status,
                message=message,
                details=detail,
                fix=None,
            )
        )
        if age_seconds is not None:
            checks[-1]["age_seconds"] = age_seconds

    if os.path.isdir(job_dir):
        job_store_ok = _safe_access(job_dir, os.W_OK)
    else:
        job_store_ok = _safe_access(os.path.dirname(job_dir) or ".", os.W_OK)
    checks.append(
        _make_check(
            check_id="storage.job_store_writable",
            label="job store",
            category="storage",
            status="ok" if job_store_ok else "warning",
            message="Writable" if job_store_ok else "Job store directory is not writable.",
            details=f"Job data is stored under {job_dir}.",
        )
    )

    # Project checks.
    config_exists = os.path.isfile(paths["config"])
    verify_cmd = cfg.get("AGYKIT_VERIFY", "").strip()
    flags = cfg.get("AGYKIT_FLAGS", "").strip()
    system_file = cfg.get("AGYKIT_SYSTEM", "").strip()
    gitignore_text = _read_text(paths["gitignore"])

    checks.append(
        _make_check(
            check_id="project.config",
            label=".agykit.conf",
            category="project",
            status="ok" if config_exists else "critical",
            message="Project config found." if config_exists else ".agykit.conf is missing.",
            details=f"{paths['config']}",
            fix={
                "type": "manual_edit",
                "file": ".agykit.conf",
                "example": 'AGYKIT_VERIFY="python3 -m pytest tests -q"',
            }
            if not config_exists
            else None,
        )
    )
    checks.append(
        _make_check(
            check_id="project.verify",
            label="AGYKIT_VERIFY",
            category="project",
            status="ok" if verify_cmd else "critical",
            message="Verification command configured." if verify_cmd else "AGYKIT_VERIFY is missing.",
            details=verify_cmd or "AGYKIT_VERIFY should point to the project verification command.",
            fix={
                "type": "manual_edit",
                "file": ".agykit.conf",
                "example": 'AGYKIT_VERIFY="python3 -m pytest tests -q"',
            }
            if not verify_cmd
            else None,
        )
    )
    checks.append(
        _make_check(
            check_id="project.flags",
            label="AGYKIT_FLAGS",
            category="project",
            status="warning" if "--dangerously-skip-permissions" in flags else "ok",
            message="Flags are broad; review them if you want stricter sandboxing."
            if "--dangerously-skip-permissions" in flags
            else "Project flags look reasonable.",
            details=flags or "AGYKIT_FLAGS is not set.",
            fix={
                "type": "manual_edit",
                "file": ".agykit.conf",
                "example": 'AGYKIT_FLAGS="--add-dir $PWD/dashboard"',
            }
            if "--dangerously-skip-permissions" in flags
            else None,
        )
    )
    checks.append(
        _make_check(
            check_id="project.system",
            label="AGYKIT_SYSTEM",
            category="project",
            status="ok" if system_file else "warning",
            message="System context configured." if system_file else "AGYKIT_SYSTEM is missing.",
            details=system_file or "AGYKIT_SYSTEM should point to the injected system prompt file.",
        )
    )
    checks.append(
        _make_check(
            check_id="project.claude_system",
            label="CLAUDE_AGY_SYSTEM.md",
            category="project",
            status="ok" if os.path.isfile(paths["system_claude"]) else "warning",
            message="Claude system prompt found."
            if os.path.isfile(paths["system_claude"])
            else "CLAUDE_AGY_SYSTEM.md is missing.",
            details=paths["system_claude"],
            fix={"type": "manual_edit", "file": "CLAUDE_AGY_SYSTEM.md"}
            if not os.path.isfile(paths["system_claude"])
            else None,
        )
    )
    checks.append(
        _make_check(
            check_id="project.gitignore",
            label=".gitignore",
            category="project",
            status="ok" if ".agykit.conf" in gitignore_text else "warning",
            message=".agykit.conf is ignored by git." if ".agykit.conf" in gitignore_text else ".gitignore does not mention .agykit.conf.",
            details=paths["gitignore"],
        )
    )

    # Agent data checks.
    agent_checks = [
        (
            "agent.claude_stats",
            "Claude stats cache",
            "agent",
            os.path.isfile(claude_stats),
            f"{claude_stats}",
        ),
        (
            "agent.claude_history",
            "Claude history",
            "agent",
            os.path.isfile(os.path.expanduser("~/.claude/history.jsonl")),
            "~/.claude/history.jsonl",
        ),
        (
            "agent.codex_history",
            "Codex history",
            "agent",
            os.path.isfile(os.path.expanduser("~/.codex/history.jsonl")),
            "~/.codex/history.jsonl",
        ),
        (
            "agent.codex_sessions",
            "Codex session index",
            "agent",
            os.path.isfile(os.path.expanduser("~/.codex/session_index.jsonl")),
            "~/.codex/session_index.jsonl",
        ),
        (
            "agent.codex_state",
            "Codex state DB",
            "agent",
            os.path.isfile(os.path.expanduser("~/.codex/state_5.sqlite")),
            "~/.codex/state_5.sqlite",
        ),
        (
            "agent.statusline",
            "Statusline snapshot",
            "agent",
            os.path.isfile(statusline),
            statusline,
        ),
    ]
    for check_id, label, category, present, detail in agent_checks:
        age_seconds = _cache_age_seconds(detail) if os.path.isabs(os.path.expanduser(detail)) and os.path.isfile(os.path.expanduser(detail)) else None
        if check_id == "agent.statusline" and age_seconds is not None and age_seconds > _CACHE_STALE_SECONDS:
            status = "stale"
            message = f"Cached data is {_format_age_seconds(age_seconds)} old."
        else:
            status = "ok" if present else "warning"
            message = "Available" if present else f"Missing: {detail}"
        checks.append(
            _make_check(
                check_id=check_id,
                label=label,
                category=category,
                status=status,
                message=message,
                details=detail,
            )
        )
        if age_seconds is not None:
            checks[-1]["age_seconds"] = age_seconds

    scope_map = {
        "system": {"dependency", "storage"},
        "project": {"project"},
        "agents": {"agent"},
        "all": {"dependency", "storage", "project", "agent"},
    }
    allowed = scope_map.get((scope or "all").lower(), scope_map["all"])
    filtered = [c for c in checks if c["category"] in allowed]
    if fixable:
        filtered = [c for c in filtered if c.get("fix")]

    passed = sum(1 for c in filtered if c["status"] == "ok")
    warnings = sum(1 for c in filtered if c["status"] in {"warning", "stale", "missing", "unknown"})
    critical = sum(1 for c in filtered if c["status"] == "critical")
    stale = any(c["status"] == "stale" for c in filtered)
    if critical:
        overall = "critical"
    elif warnings:
        overall = "warning"
    else:
        overall = "ok"

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "source": "agykit",
        "stale": False,
        "overall_status": overall,
        "stale": stale,
        "summary": {"passed": passed, "warnings": warnings, "critical": critical},
        "checks": filtered,
    }


def _parse_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _latest_job_id() -> str | None:
    jobs = job_list(limit=1)
    if not jobs:
        return None
    return jobs[0].get("job_id")


def _select_timeline_job(job_id: str | None) -> tuple[str | None, dict | None, list[dict]]:
    selected = job_id or _latest_job_id()
    if not selected:
        return None, None, []
    snapshot = job_snapshot(selected)
    if snapshot is None:
        return selected, None, []
    events = job_events(selected, limit=500)
    return selected, snapshot, events


def _timeline_label(event: str) -> str:
    labels = {
        "job_started": "Started",
        "account_selected": "Account Selected",
        "account_switched": "Account Switched",
        "model_selected": "Model Selected",
        "model_escalated": "Model Escalated",
        "model_retried": "Model Retried",
        "prompt_dispatched": "Prompt Dispatched",
        "verify_started": "Verification Started",
        "verify_passed": "Verification Passed",
        "verify_failed": "Verification Failed",
        "quota_rotated": "Quota Rotated",
        "rollback_started": "Rollback Started",
        "rollback_finished": "Rollback Finished",
        "rollback_failed": "Rollback Failed",
        "job_succeeded": "Succeeded",
        "job_failed": "Failed",
        "job_blocked": "Blocked",
        "job_cancelled": "Cancelled",
        "job_timed_out": "Timed Out",
    }
    if event in labels:
        return labels[event]
    return event.replace("_", " ").title()


def _timeline_status(event: str, snapshot_status: str, is_last: bool) -> str:
    if event in {"job_failed", "job_blocked", "job_cancelled", "job_timed_out", "verify_failed", "rollback_failed"}:
        return "failed"
    if is_last and snapshot_status in _ACTIVE_JOB_STATUSES:
        return "active"
    return "completed"


def _timeline_severity(event: str) -> str:
    if event in {"job_failed", "job_blocked", "job_cancelled", "job_timed_out"}:
        return "critical"
    if event in {"verify_failed", "rollback_started", "rollback_failed", "quota_rotated"}:
        return "warning"
    if event in {"job_succeeded", "verify_passed", "rollback_finished"}:
        return "success"
    return "info"


def job_timeline(job_id: str | None = None, *, limit: int = 100) -> dict:
    selected_job_id, snapshot, events = _select_timeline_job(job_id)
    if not snapshot:
        return {
            "ok": True,
            "generated_at": _now_iso(),
            "source": "agykit",
            "stale": False,
            "job_id": selected_job_id,
            "snapshot": None,
            "timeline": [],
            "metrics": {
                "elapsed_seconds": None,
                "attempt_count": 0,
                "model_switch_count": 0,
                "account_switch_count": 0,
                "rollback_count": 0,
                "verify_fail_count": 0,
            },
            "warning": "No job found" if selected_job_id is None else "Job not found",
        }

    events = events[-limit:]
    snapshot_status = snapshot.get("status", "")
    started_at = _parse_iso(snapshot.get("started_at"))
    ended_at = _parse_iso(snapshot.get("ended_at"))
    current_ts = _dt.datetime.now(_dt.timezone.utc)
    elapsed_seconds = None
    if started_at:
        elapsed_seconds = int(((ended_at or current_ts) - started_at).total_seconds())

    timeline: list[dict] = []
    prev_ts: _dt.datetime | None = None
    account_switches = 0
    model_switches = 0
    rollback_count = 0
    verify_fail_count = 0
    attempts = 0
    last_account = None
    last_model = None

    for idx, event in enumerate(events, start=1):
        event_name = event.get("event", "")
        event_ts = _parse_iso(event.get("ts"))
        duration_ms = None
        if event_ts and prev_ts:
            duration_ms = int((event_ts - prev_ts).total_seconds() * 1000)
        prev_ts = event_ts or prev_ts

        if event_name == "job_started":
            attempts += 1
        if event_name in {"account_selected", "account_switched"} and event.get("account") != last_account:
            account_switches += 1
            last_account = event.get("account")
        if event_name in {"model_selected", "model_escalated", "model_retried"} and event.get("model") != last_model:
            model_switches += 1
            last_model = event.get("model")
        if event_name.startswith("rollback_"):
            rollback_count += 1
        if event_name == "verify_failed":
            verify_fail_count += 1

        timeline.append(
            {
                "seq": idx,
                "event": event_name,
                "label": _timeline_label(event_name),
                "timestamp": event.get("ts"),
                "status": _timeline_status(event_name, snapshot_status, idx == len(events)),
                "severity": _timeline_severity(event_name),
                "duration_ms": duration_ms,
                "account": event.get("account"),
                "model": event.get("model"),
                "stage": event.get("stage"),
                "message": event.get("message", ""),
                "error": event.get("error"),
            }
        )

    if not attempts and events:
        attempts = 1

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "source": "agykit",
        "stale": False,
        "job_id": selected_job_id,
        "snapshot": snapshot,
        "timeline": timeline,
        "metrics": {
            "elapsed_seconds": elapsed_seconds,
            "attempt_count": attempts,
            "model_switch_count": model_switches,
            "account_switch_count": account_switches,
            "rollback_count": rollback_count,
            "verify_fail_count": verify_fail_count,
        },
        "warning": None,
    }


def _load_job_history(days: int = 30, limit: int = 500) -> list[dict]:
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    history = []
    for job in job_list(limit=limit):
        started_at = _parse_iso(job.get("started_at"))
        if started_at and started_at >= cutoff:
            history.append(job)
    return history


def _group_job_history(history: Iterable[dict]) -> dict[tuple[str, str], dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for job in history:
        account = job.get("account") or ""
        model = job.get("model") or ""
        model_keys = _model_match_keys(model)
        if not account and not model_keys:
            continue
        status = job.get("status") or ""
        duration = float(job.get("duration_seconds") or 0) if job.get("duration_seconds") is not None else None
        started_at = _parse_iso(job.get("started_at"))
        verify_failed = 1 if (job.get("error_category") or "") == "verify" else 0
        for model_key in model_keys:
            key = (account, model_key)
            bucket = grouped.setdefault(
                key,
                {
                    "jobs": 0,
                    "success": 0,
                    "failed": 0,
                    "blocked": 0,
                    "durations": [],
                    "last_used": None,
                    "verify_failed": 0,
                },
            )
            bucket["jobs"] += 1
            if status == "succeeded":
                bucket["success"] += 1
            elif status == "blocked":
                bucket["blocked"] += 1
            elif status == "failed":
                bucket["failed"] += 1
            if duration is not None:
                bucket["durations"].append(duration)
            if started_at and (bucket["last_used"] is None or started_at > bucket["last_used"]):
                bucket["last_used"] = started_at
            if verify_failed:
                bucket["verify_failed"] += 1
    return grouped


def _recent_job_counts(history: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for job in history:
        key = job.get("status") or "unknown"
        counts[key] += 1
    return counts


def _normalise_score(value: float | None, default: float = 60.0) -> float:
    if value is None:
        return default
    return max(0.0, min(100.0, float(value)))


def _model_family(model: str) -> str:
    name = (model or "").lower()
    if "opus" in name or "pro" in name:
        return "strong"
    if "flash" in name or "haiku" in name or "mini" in name:
        return "fast"
    return "general"


def _model_match_keys(model: str) -> list[str]:
    raw = re.sub(r"[^a-z0-9]+", " ", (model or "").lower()).strip()
    keys: list[str] = []
    if raw:
        keys.append(raw)

    family = _model_family(model)
    if family and family not in keys:
        keys.append(family)

    return keys


def _lookup_job_history(grouped: dict[tuple[str, str], dict], account: str, model: str) -> dict | None:
    account_key = account or ""
    for model_key in _model_match_keys(model):
        hist = grouped.get((account_key, model_key))
        if hist:
            return hist
    return None


def _default_model_for_mode(mode: str) -> str:
    if mode == "aggressive":
        return "gemini-2.5-pro"
    if mode == "cost_saving":
        return "gemini-2.5-flash"
    return "gemini-2.5-flash"


def _score_weights(mode: str) -> dict[str, float]:
    mode = (mode or "balanced").lower()
    if mode == "cost_saving":
        return {
            "quota": 0.45,
            "reliability": 0.20,
            "speed": 0.10,
            "freshness": 0.05,
            "project_fit": 0.10,
            "penalty": 0.10,
        }
    if mode == "speed":
        return {
            "quota": 0.20,
            "reliability": 0.20,
            "speed": 0.30,
            "freshness": 0.10,
            "project_fit": 0.10,
            "penalty": 0.10,
        }
    if mode == "reliability":
        return {
            "quota": 0.20,
            "reliability": 0.40,
            "speed": 0.10,
            "freshness": 0.05,
            "project_fit": 0.15,
            "penalty": 0.10,
        }
    if mode == "aggressive":
        return {
            "quota": 0.15,
            "reliability": 0.30,
            "speed": 0.10,
            "freshness": 0.05,
            "project_fit": 0.30,
            "penalty": 0.10,
        }
    return {
        "quota": 0.35,
        "reliability": 0.25,
        "speed": 0.15,
        "freshness": 0.10,
        "project_fit": 0.10,
        "penalty": 0.05,
    }


def _score_candidate(
    *,
    account: dict,
    model: dict,
    hist: dict | None,
    verify_fail_pressure: int,
    active_email: str | None,
    mode: str,
) -> tuple[float, dict, list[str], list[str]]:
    weights = _score_weights(mode)
    model_name = model.get("model_id") or model.get("display_name") or ""
    pct = model.get("pct_remaining")
    if pct is None:
        pct = model.get("remaining_fraction")
        if pct is not None:
            pct *= 100
    quota_score = 50.0 if pct is None else float(pct)
    if account.get("status") == "exhausted" or (pct is not None and pct <= 0):
        quota_score = 0.0

    reliability_score = 60.0
    speed_score = 60.0
    freshness_score = 60.0
    project_fit_score = 60.0
    penalty_adjustment = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    if hist:
        jobs = hist["jobs"]
        if jobs > 0:
            total_terminal = hist["success"] + hist["failed"] + hist["blocked"]
            if total_terminal > 0:
                reliability_score = (hist["success"] / total_terminal) * 100.0
            durations = hist["durations"]
            if durations:
                avg_dur = sum(durations) / len(durations)
                speed_score = max(0.0, 100.0 - min(100.0, avg_dur / 120.0))
            last_used = hist["last_used"]
            if last_used:
                age_days = max(0.0, (_dt.datetime.now(_dt.timezone.utc) - last_used).total_seconds() / 86400)
                freshness_score = max(30.0, 100.0 - age_days * 10.0)
            if hist["verify_failed"]:
                warnings.append(f"{account['email']} / {model_name} has {hist['verify_failed']} verify failure(s) in recent history.")
                project_fit_score = 80.0 if _model_family(model_name) == "strong" else 65.0
            else:
                project_fit_score = 82.0 if _model_family(model_name) == "fast" else 74.0
        else:
            warnings.append("No recent history for this pair; using defaults.")

    if verify_fail_pressure > 0 and _model_family(model_name) == "strong":
        project_fit_score = max(project_fit_score, 88.0)
        reasons.append("Recent verification failures favour a stronger model.")
    elif verify_fail_pressure == 0 and _model_family(model_name) == "fast":
        project_fit_score = max(project_fit_score, 85.0)
        reasons.append("No recent verify pressure; a fast model is a good fit.")

    if active_email and account.get("email") == active_email:
        freshness_score = min(100.0, freshness_score + 8.0)
        reasons.append("Matches the current active account.")

    if pct is not None:
        reasons.append(f"Remaining quota is {pct:.0f}%.")
    else:
        reasons.append("Quota data is unavailable; using defaults.")

    if reliability_score >= 80:
        reasons.append(f"Recent success rate is {reliability_score:.0f}%.")
    elif reliability_score < 60:
        penalty_adjustment -= 12.0
        warnings.append("Recent reliability is weak.")

    if pct is not None and pct < 20:
        penalty_adjustment -= 15.0
        warnings.append("Quota is below the warning threshold.")
    if account.get("status") == "exhausted":
        penalty_adjustment -= 100.0
        warnings.append("Account is exhausted.")

    if account.get("exhaustion_count", 0) > 0:
        penalty_adjustment -= min(8.0, float(account.get("exhaustion_count", 0)))

    score = (
        weights["quota"] * quota_score
        + weights["reliability"] * reliability_score
        + weights["speed"] * speed_score
        + weights["freshness"] * freshness_score
        + weights["project_fit"] * project_fit_score
        + weights["penalty"] * penalty_adjustment
    )

    confidence = int(round(max(0.0, min(100.0, score))))
    risk = "low"
    if account.get("status") == "exhausted" or confidence < 35 or (pct is not None and pct < 10):
        risk = "critical"
    elif confidence < 60 or (pct is not None and pct < 20):
        risk = "high"
    elif confidence < 78:
        risk = "medium"

    payload = {
        "account": account.get("email"),
        "model": model_name or _default_model_for_mode(mode),
        "confidence": confidence,
        "risk": risk,
        "reason": reasons,
        "warnings": warnings,
        "score": round(score, 2),
        "quota_score": round(quota_score, 2),
        "reliability_score": round(reliability_score, 2),
        "speed_score": round(speed_score, 2),
        "freshness_score": round(freshness_score, 2),
        "project_fit_score": round(project_fit_score, 2),
    }
    return score, payload, reasons, warnings


def recommended_account_model(
    *,
    mode: str = "balanced",
    project_dir: str | None = None,
) -> dict:
    project_root = os.path.abspath(project_dir or os.getcwd())
    cfg = _parse_shell_assignments(os.path.join(project_root, ".agykit.conf"))
    verify_enabled = bool(cfg.get("AGYKIT_VERIFY") or os.environ.get("AGYKIT_VERIFY"))
    quota_cache_path = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")

    account_status = agy_quota_status().get("accounts", [])
    account_status_map = {a.get("email"): a for a in account_status if a.get("email")}

    try:
        model_quota = agy_model_quota()
    except Exception:
        model_quota = agy_model_quota_cached(force=False)

    if not model_quota.get("accounts"):
        cached = agy_model_quota_cached(force=False)
        if cached.get("models"):
            active = agy_active_account().get("email") or agy_statusline_snapshot().get("email")
            model_quota = {
                "accounts": [
                    {
                        "email": active or next(iter(account_status_map), None) or "unknown",
                        "models": cached.get("models", []),
                        "error": cached.get("warning"),
                    }
                ],
                "warning": cached.get("warning"),
            }

    history = _load_job_history(days=30, limit=500)
    grouped = _group_job_history(history)
    verify_pressure = job_stats().get("error_breakdown", {}).get("verify", 0)
    active_email = agy_active_account().get("email") or agy_statusline_snapshot().get("email")

    candidates: list[dict] = []
    for acct in model_quota.get("accounts", []):
        email = acct.get("email")
        if not email:
            continue
        account_meta = dict(account_status_map.get(email, {}))
        account_meta.setdefault("email", email)
        account_meta.setdefault("status", "available")
        account_meta.setdefault("exhaustion_count", 0)
        account_meta.setdefault("session_count", 0)
        models = acct.get("models") or []
        if not models:
            models = [
                {"model_id": _default_model_for_mode(mode), "display_name": _default_model_for_mode(mode), "pct_remaining": None},
                {"model_id": "gemini-2.5-pro", "display_name": "gemini-2.5-pro", "pct_remaining": None},
            ]
        for model in models:
            hist = _lookup_job_history(grouped, email, model.get("model_id") or model.get("display_name") or "")
            score, payload, _, warnings = _score_candidate(
                account=account_meta,
                model=model,
                hist=hist,
                verify_fail_pressure=verify_pressure if verify_enabled else 0,
                active_email=active_email,
                mode=mode,
            )
            payload["command"] = f"agykit switch {email} && agykit model {payload['model']}"
            payload["_score"] = score
            candidates.append(payload)

    if not candidates:
        quota_cache_age = _cache_age_seconds(quota_cache_path)
        return {
            "ok": True,
            "generated_at": _now_iso(),
            "source": "agykit",
            "stale": quota_cache_age is not None and quota_cache_age > _CACHE_STALE_SECONDS,
            "mode": mode,
            "quota_cache_age_seconds": quota_cache_age,
            "recommendation": {
                "account": None,
                "model": _default_model_for_mode(mode),
                "confidence": 0,
                "risk": "unknown",
                "reason": ["No account/model data available."],
                "warnings": ["Unable to compute a recommendation."],
                "command": None,
            },
            "alternatives": [],
            "rejected": [],
            "signals": _score_weights(mode),
            "warning": "No account/model data available",
        }

    candidates.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
    best = candidates[0]
    alternatives = candidates[1:4]
    rejected = [
        {
            "account": c.get("account"),
            "model": c.get("model"),
            "reason": "Quota is below warning threshold." if c.get("quota_score", 100) < 20 else "Lower score than the recommended pair.",
        }
        for c in candidates[4:8]
    ]

    reason = list(best.get("reason", []))
    if verify_enabled and verify_pressure:
        reason.append("Recent verify failures influenced the ranking.")
    if best.get("quota_score", 100) >= 80:
        reason.append("This pair has the strongest quota headroom.")

    quota_cache_age = model_quota.get("_cache_age_seconds")
    if quota_cache_age is None:
        quota_cache_age = _cache_age_seconds(quota_cache_path)

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "source": "agykit",
        "stale": quota_cache_age is not None and quota_cache_age > _CACHE_STALE_SECONDS,
        "mode": mode,
        "quota_cache_age_seconds": quota_cache_age,
        "recommendation": {
            "account": best.get("account"),
            "model": best.get("model"),
            "confidence": best.get("confidence", 0),
            "risk": best.get("risk", "unknown"),
            "reason": reason,
            "warnings": best.get("warnings", []),
            "command": best.get("command"),
        },
        "alternatives": [
            {
                "account": item.get("account"),
                "model": item.get("model"),
                "confidence": item.get("confidence", 0),
                "risk": item.get("risk", "unknown"),
                "reason": item.get("reason", []),
                "command": item.get("command"),
            }
            for item in alternatives
        ],
        "rejected": rejected,
        "signals": _score_weights(mode),
        "warning": None,
    }


def _risk_from_eta(eta_hours: float | None, remaining_percent: float | None) -> str:
    if remaining_percent is None:
        return "unknown"
    if remaining_percent < 10 or (eta_hours is not None and eta_hours < 1):
        return "critical"
    if remaining_percent < 20 or (eta_hours is not None and eta_hours < 3):
        return "high"
    if remaining_percent < 60 or (eta_hours is not None and eta_hours < 12):
        return "medium"
    return "low"


def _format_eta(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours <= 0:
        return "<1h"
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    if h >= 24:
        return f">{h // 24}d"
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def quota_forecast(
    *,
    window: str = "24h",
    strategy: str = "hybrid",
) -> dict:
    try:
        hours = int(window.rstrip("h"))
    except Exception:
        hours = 24
    if hours <= 0:
        hours = 24

    history = _load_job_history(days=max(1, min(30, hours // 24 + 1 if hours >= 24 else 1)), limit=500)
    grouped = _group_job_history(history)
    total_history_jobs = len(history)
    quota_cache_path = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")

    try:
        quota_data = agy_model_quota()
    except Exception:
        quota_data = agy_model_quota_cached(force=False)

    accounts: list[dict] = []
    overall_risk_rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    overall_risk = "unknown"
    recommendations: list[str] = []

    for acct in quota_data.get("accounts", []):
        email = acct.get("email")
        models = acct.get("models") or []
        account_block = {"account": email, "models": []}
        best_model: dict | None = None
        for model in models:
            model_name = model.get("model_id") or model.get("display_name") or ""
            quota_pct = model.get("pct_remaining")
            if quota_pct is None and model.get("remaining_fraction") is not None:
                quota_pct = float(model.get("remaining_fraction") or 0) * 100.0
            quota_pct = None if quota_pct is None else float(quota_pct)

            hist = _lookup_job_history(grouped, email or "", model_name)
            job_count = hist["jobs"] if hist else 0
            fail_count = (hist["failed"] + hist["blocked"]) if hist else 0
            total_hours = max(1.0, hours)
            jobs_per_hour = job_count / total_hours if total_hours > 0 else 0.0
            base_rate = jobs_per_hour * 4.0
            failure_pressure = (fail_count / job_count * 1.5) if job_count else 0.0
            burn_rate = round(max(0.5, base_rate + failure_pressure), 2) if quota_pct is not None else None

            avg_duration = None
            if hist and hist["durations"]:
                avg_duration = sum(hist["durations"]) / len(hist["durations"])

            eta_hours = (quota_pct / burn_rate) if quota_pct is not None and burn_rate and burn_rate > 0 else None
            if eta_hours is not None and avg_duration:
                estimated_jobs_remaining = int(max(0, round((eta_hours * 3600) / avg_duration)))
            elif eta_hours is not None and jobs_per_hour > 0:
                estimated_jobs_remaining = int(max(0, round(eta_hours * jobs_per_hour)))
            elif quota_pct is not None and job_count:
                estimated_jobs_remaining = int(max(0, round(quota_pct / max(1.0, 100.0 / max(1, job_count)))))
            elif quota_pct is not None and total_history_jobs > 0:
                estimated_jobs_remaining = int(max(0, round((quota_pct / 100.0) * max(1, total_history_jobs))))
            else:
                estimated_jobs_remaining = None

            risk = _risk_from_eta(eta_hours, quota_pct)
            confidence = "high" if hist and hist["jobs"] >= 5 else "medium" if hist and hist["jobs"] >= 2 else "low"
            notes = [f"Forecast based on the last {hours}h of local job history."]
            if hist and hist["jobs"]:
                notes.append(f"Matched {hist['jobs']} recent jobs for this account/model family.")
            if burn_rate is not None:
                notes.append(f"Estimated burn rate: {burn_rate:.1f}%/hour.")
            if hist and hist["verify_failed"]:
                notes.append("Recent verify failures increase risk.")

            model_entry = {
                "model": model_name,
                "remaining_percent": round(quota_pct, 1) if quota_pct is not None else None,
                "burn_rate_percent_per_hour": burn_rate,
                "eta_hours": round(eta_hours, 1) if eta_hours is not None else None,
                "eta_label": _format_eta(eta_hours),
                "estimated_jobs_remaining": estimated_jobs_remaining,
                "risk": risk,
                "confidence": confidence,
                "notes": notes,
                "reset_in_seconds": model.get("resets_in_seconds") or 0,
            }
            account_block["models"].append(model_entry)

            if best_model is None:
                best_model = model_entry
            else:
                current_rank = overall_risk_rank.get(best_model["risk"], 0)
                new_rank = overall_risk_rank.get(risk, 0)
                if new_rank > current_rank:
                    best_model = model_entry

        accounts.append(account_block)
        if best_model:
            if overall_risk_rank.get(best_model["risk"], 0) > overall_risk_rank.get(overall_risk, 0):
                overall_risk = best_model["risk"]

    if accounts:
        for acct in accounts:
            for model in acct["models"]:
                if model["risk"] in {"high", "critical"}:
                    recommendations.append(
                        f"Preserve {acct['account']} / {model['model']} for verification retries and difficult refactors."
                    )
                elif model["risk"] == "medium":
                    recommendations.append(
                        f"Use {acct['account']} / {model['model']} for routine work while quota remains healthy."
                    )

    if not recommendations:
        best_candidate: tuple[tuple[int, float, str, str], str, str] | None = None
        for acct in accounts:
            for model in acct["models"]:
                candidate = (
                    -overall_risk_rank.get(model["risk"], 0),
                    float(model.get("remaining_percent") if model.get("remaining_percent") is not None else -1),
                    acct.get("account") or "",
                    model.get("model") or "",
                )
                if best_candidate is None or candidate > best_candidate[0]:
                    best_candidate = (candidate, acct.get("account") or "", model.get("model") or "")
        if best_candidate:
            _, account_name, model_name = best_candidate
            recommendations.append(
                f"Use {account_name} / {model_name} for routine work; preserve stronger models for verification retries."
            )

    if not accounts:
        overall_risk = "unknown"

    quota_cache_age = quota_data.get("_cache_age_seconds")
    if quota_cache_age is None:
        quota_cache_age = _cache_age_seconds(quota_cache_path)

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "source": "agykit",
        "stale": quota_cache_age is not None and quota_cache_age > _CACHE_STALE_SECONDS,
        "window": window,
        "quota_cache_age_seconds": quota_cache_age,
        "overall_risk": overall_risk,
        "accounts": accounts,
        "recommendations": recommendations[:6],
        "warning": quota_data.get("warning"),
    }


def _agent_tokens_per_success(
    tokens_total: int | None,
    jobs_succeeded: int | None,
    jobs_total: int | None,
) -> int | None:
    if tokens_total is None:
        return None
    if jobs_succeeded:
        return int(round(tokens_total / jobs_succeeded))
    if jobs_total:
        return int(round(tokens_total / jobs_total))
    return None


def _normalize_distribution(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 2) for k, v in sorted(counter.items(), key=lambda item: (-item[1], item[0]))}


def agent_performance_matrix(
    *,
    range_key: str = "7d",
) -> dict:
    if range_key == "24h":
        days = 1
    elif range_key == "30d":
        days = 30
    else:
        days = 7

    history = _load_job_history(days=days, limit=500)
    job_total = len(history)
    job_models = Counter((job.get("model") or "unknown") for job in history if job.get("model"))
    job_accounts = Counter((job.get("account") or "unknown") for job in history if job.get("account"))
    top_model = job_models.most_common(1)[0][0] if job_models else None
    agy_tokens_total = None

    agy_success = sum(1 for job in history if job.get("status") == "succeeded")
    agy_failed = sum(1 for job in history if job.get("status") == "failed")
    agy_blocked = sum(1 for job in history if job.get("status") == "blocked")
    agy_terminal = agy_success + agy_failed + agy_blocked
    agy_success_rate = round((agy_success / agy_terminal) * 100, 1) if agy_terminal else None

    agy_durations = [float(job.get("duration_seconds") or 0) for job in history if job.get("duration_seconds") is not None]
    agy_avg_duration = round(sum(agy_durations) / len(agy_durations), 1) if agy_durations else None
    agy_verify_failures = sum(1 for job in history if (job.get("error_category") or "") == "verify")

    agy_agent = {
        "agent": "agy",
        "jobs_total": job_total,
        "jobs_succeeded": agy_success,
        "jobs_failed": agy_failed + agy_blocked,
        "success_rate": agy_success_rate,
        "tokens_total": agy_tokens_total,
        "avg_duration_seconds": agy_avg_duration,
        "verify_failures": agy_verify_failures,
        "rollback_count": None,
        "tokens_per_success": _agent_tokens_per_success(agy_tokens_total, agy_success, job_total),
        "top_model": top_model,
        "model_distribution": _normalize_distribution(job_models),
        "risk_notes": [],
        "confidence": "high" if job_total >= 5 else "medium" if job_total >= 2 else "low",
    }
    if agy_success_rate is not None and agy_success_rate < 85:
        agy_agent["risk_notes"].append("Success rate is below 85%.")
    if agy_agent["verify_failures"]:
        agy_agent["risk_notes"].append("Verify failures still occur in local jobs.")
    if agy_agent["tokens_per_success"] is None:
        agy_agent["risk_notes"].append("Token efficiency data is unavailable for agy jobs.")

    codex = codex_usage(limit=10)
    codex_summary = codex.get("summary", {})
    codex_models = Counter(thread.get("model") or "unknown" for thread in codex.get("recent_threads", []) if thread.get("model"))
    codex_agent = {
        "agent": "codex",
        "jobs_total": codex_summary.get("sessions", 0),
        "jobs_succeeded": None,
        "jobs_failed": None,
        "success_rate": None,
        "tokens_total": codex_summary.get("tokens_used", 0),
        "avg_duration_seconds": None,
        "verify_failures": None,
        "rollback_count": None,
        "tokens_per_success": _agent_tokens_per_success(codex_summary.get("tokens_used", 0), None, codex_summary.get("sessions", 0)),
        "top_model": codex_summary.get("models", [None])[0] if codex_summary.get("models") else (codex.get("recent_threads", [{}])[0].get("model") if codex.get("recent_threads") else None),
        "model_distribution": _normalize_distribution(codex_models),
        "risk_notes": [codex.get("warning")] if codex.get("warning") else [],
        "confidence": "high" if codex_summary.get("sessions", 0) >= 5 else "medium" if codex_summary.get("sessions", 0) >= 2 else "low",
    }
    if codex_agent["tokens_per_success"] is not None:
        codex_agent["risk_notes"].append("Efficiency uses session count because success totals are not exposed by Codex data.")

    claude_series_data = claude_series(range_key="30d")
    claude_quota_data = claude_quota()
    claude_total_tokens = sum(claude_series_data.get("tokens_total", []))
    claude_models = Counter()
    for model, values in (claude_series_data.get("tokens_by_model") or {}).items():
        claude_models[model] += sum(values)
    claude_sessions = sum(claude_series_data.get("sessions", []))
    claude_agent = {
        "agent": "Claude Code",
        "jobs_total": claude_sessions,
        "jobs_succeeded": None,
        "jobs_failed": None,
        "success_rate": None,
        "tokens_total": claude_total_tokens,
        "avg_duration_seconds": None,
        "verify_failures": None,
        "rollback_count": None,
        "tokens_per_success": _agent_tokens_per_success(claude_total_tokens, None, claude_sessions),
        "top_model": claude_models.most_common(1)[0][0] if claude_models else None,
        "model_distribution": _normalize_distribution(claude_models),
        "risk_notes": [claude_quota_data.get("warning")] if claude_quota_data.get("warning") else [],
        "confidence": "high" if claude_sessions >= 5 else "medium" if claude_sessions >= 2 else "low",
    }
    if claude_agent["tokens_per_success"] is not None:
        claude_agent["risk_notes"].append("Efficiency uses session count because Claude does not expose success totals here.")

    opencode_home = os.path.expanduser(os.environ.get("AGYKIT_DASH_OPENCODE_HOME", "~/.config/opencode"))
    opencode_history_candidates = [
        os.path.join(opencode_home, "history.jsonl"),
        os.path.expanduser("~/.opencode/history.jsonl"),
        os.path.join(opencode_home, "sessions", "history.jsonl"),
    ]
    opencode_history = next((p for p in opencode_history_candidates if os.path.isfile(p)), None)
    opencode_count = 0
    if opencode_history:
        try:
            with open(opencode_history, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip():
                        opencode_count += 1
        except Exception:
            opencode_count = 0
    opencode_agent = {
        "agent": "OpenCode",
        "jobs_total": opencode_count,
        "jobs_succeeded": None,
        "jobs_failed": None,
        "success_rate": None,
        "tokens_total": None,
        "avg_duration_seconds": None,
        "verify_failures": None,
        "rollback_count": None,
        "tokens_per_success": None,
        "top_model": None,
        "model_distribution": {},
        "risk_notes": ["No local OpenCode history found."] if not opencode_history else [],
        "confidence": "low" if not opencode_history else "medium",
    }

    agents = [agy_agent, codex_agent, claude_agent, opencode_agent]
    known_success = [a for a in agents if a.get("success_rate") is not None]
    known_tokens = [a for a in agents if a.get("tokens_per_success") is not None]
    known_fail = [a for a in agents if a.get("jobs_failed") is not None and a.get("jobs_total")]

    summary = {
        "best_success_rate": max(known_success, key=lambda a: a["success_rate"])["agent"] if known_success else None,
        "lowest_tokens_per_success": min(known_tokens, key=lambda a: a["tokens_per_success"])["agent"] if known_tokens else None,
        "highest_failure_rate": None,
        "most_used_agent": max(agents, key=lambda a: a.get("jobs_total") or 0)["agent"] if agents else None,
    }
    if known_fail:
        summary["highest_failure_rate"] = max(
            known_fail,
            key=lambda a: ((a.get("jobs_failed") or 0) / max(1, a.get("jobs_total") or 1)),
        )["agent"]

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "source": "agykit",
        "stale": False,
        "range": range_key,
        "agents": agents,
        "summary": summary,
        "warning": None,
    }
