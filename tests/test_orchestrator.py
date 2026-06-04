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


def test_run_agy_transient_on_nonzero_exit():
    """Non-zero exit + no quota → transient_error."""
    orch = ConcreteOrchestrator(job_id="j1", accounts=["a@b.com"], prompt="hi")
    proc = make_proc([b"ConnectionError: refused\n"], returncode=1)
    with patch("subprocess.Popen", return_value=proc):
        result = orch.run_agy("hi", [])
    assert result.transient_error
    assert not result.quota_hit
