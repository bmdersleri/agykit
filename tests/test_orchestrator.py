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


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines) + [b""]
        self._idx = 0

    def readline(self):
        if self._idx >= len(self._lines):
            return b""
        line = self._lines[self._idx]
        self._idx += 1
        return line


def make_proc(lines: list[bytes], returncode: int = 0):
    """Return a mock Popen whose stdout supports readline."""
    mock = MagicMock()
    mock.stdout = _FakeStdout(lines)
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


from dashboard.orchestrator import RunOrchestrator, EscalateOrchestrator, invalidate_quota_cache


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
    mock_log.assert_called_once_with("run", "success", "acct1@g.com", "", "do task")


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


def test_run_agy_transient_on_nonzero_exit():
    """Non-zero exit + no quota → transient_error."""
    orch = ConcreteOrchestrator(job_id="j1", accounts=["a@b.com"], prompt="hi")
    proc = make_proc([b"ConnectionError: refused\n"], returncode=1)
    with patch("subprocess.Popen", return_value=proc):
        result = orch.run_agy("hi", [])
    assert result.transient_error
    assert not result.quota_hit
