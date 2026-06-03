import os
import json
import socket
import time as _time
from datetime import datetime, timezone

try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Static, RichLog
    from textual.containers import Container
    from textual.worker import Worker, WorkerState, get_current_worker

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False


if HAS_TEXTUAL:

    class JobWatchApp(App):
        CSS = """
        #info-panel {
            border: solid $primary;
            padding: 0 1;
            height: 7;
        }
        #event-log {
            border: solid $secondary;
            height: 1fr;
        }
        """

        def __init__(self, job_id: str):
            super().__init__()
            self.job_id = job_id
            self.snap = {}
            self.events = []
            self._sock = None
            self._sock_path = None

        def compose(self):
            yield Header(name=f"agykit Job Monitor — {self.job_id}")
            with Container(id="info-panel"):
                yield Static(id="job-info")
            yield RichLog(id="event-log", highlight=True, markup=True)
            yield Footer()

        def on_mount(self):
            self._load_initial()
            self.run_worker(self._poller, thread=True)

        def _load_initial(self):
            from dashboard.collectors.jobs import job_snapshot, job_events, _JOB_SOCKET

            self.snap = job_snapshot(self.job_id) or {}
            self.events = job_events(self.job_id, limit=100)
            self._update_display()
            if os.path.exists(_JOB_SOCKET):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                    s.settimeout(0.5)
                    self._sock_path = _JOB_SOCKET + f".{os.getpid()}.tui"
                    s.bind(self._sock_path)
                    self._sock = s
                except Exception:
                    self._sock = None

        def _update_display(self):
            s = self.snap
            lines = []
            lines.append(
                f"[bold]Job:[/] {s.get('job_id', '\u2014')}    [bold]Status:[/] {s.get('status', '\u2014')}"
            )
            cmd = (s.get("command", "") or "")[:50]
            stage = (s.get("stage", "") or "")[:30]
            lines.append(f"[bold]Cmd:[/]  {cmd:<48} [bold]Stage:[/] {stage}")
            acct = s.get("account") or "\u2014"
            model = s.get("model") or "\u2014"
            lines.append(f"[bold]Acct:[/] {acct:<48} [bold]Model:[/] {model}")
            started = s.get("started_at", "")
            elapsed = "\u2014"
            if started:
                try:
                    ts = datetime.fromisoformat(started)
                    delta = datetime.now(timezone.utc) - ts
                    m = int(delta.total_seconds() // 60)
                    secs = int(delta.total_seconds() % 60)
                    elapsed = f"{m}m {secs}s"
                except Exception:
                    pass
            ended = s.get("ended_at") or "\u2014"
            lines.append(f"[bold]Elapsed:[/] {elapsed:<44} [bold]Ended:[/] {ended}")
            if s.get("last_error"):
                lines.append(f"[red]Error:[/] {s['last_error']}")
            self.query_one("#job-info", Static).update("\n".join(lines))

            log = self.query_one("#event-log", RichLog)
            log.clear()
            for e in self.events[-20:]:
                ts = e.get("ts", "")[-8:]
                evt = e.get("event", "")[:18].ljust(18)
                st = e.get("status", "")[:10].ljust(10)
                msg = (e.get("message", "") or "")[:60]
                log.write(f"{ts}  {evt} {st} {msg}")

        def _poller(self):
            worker = get_current_worker()
            from dashboard.collectors.jobs import job_snapshot, job_events

            while not worker.is_cancelled:
                got_data = False
                if self._sock is not None:
                    try:
                        data = self._sock.recv(4096)
                        got_data = True
                    except socket.timeout:
                        pass
                if got_data or self._sock is None:
                    new_snap = job_snapshot(self.job_id)
                    if new_snap:
                        self.snap = new_snap
                    self.events = job_events(self.job_id, limit=100)
                    self.call_from_thread(self._update_display)
                    if self.snap.get("status") in ("succeeded", "failed", "blocked"):
                        _time.sleep(3)
                        self.call_from_thread(self.exit, 0)
                        return
                _time.sleep(1)

        def on_worker_state_changed(self, event):
            if event.state == WorkerState.ERROR:
                self.exit(1)

        def action_quit(self):
            try:
                if self._sock is not None:
                    self._sock.close()
                    if self._sock_path and os.path.exists(self._sock_path):
                        os.unlink(self._sock_path)
            except Exception:
                pass
            super().action_quit()

    def watch_job_tui(job_id: str) -> bool:
        app = JobWatchApp(job_id)
        app.run()
        return True

else:

    def watch_job_tui(job_id: str) -> bool:
        return False
