import os
import sys
import json
import glob
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# Always import from the repo containing this server.py — not from cwd
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)
from dashboard import collectors  # noqa: E402
from dashboard.state import resolve_job_state  # noqa: E402


def _read_agykit_version():
    try:
        with open(os.path.join(_REPO_DIR, "agykit"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^AGYKIT_VERSION="([^"]+)"\s*$', line.strip())
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "unknown"


def _get_mtime(path):
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except Exception:
        return 0.0


def _newest_glob(pattern):
    try:
        files = glob.glob(pattern)
        return max(os.path.getmtime(f) for f in files) if files else 0.0
    except Exception:
        return 0.0


_MTIME_CACHE = {}


def _check_mtimes():
    """Return dict of changed source types since last call."""
    changes = {}
    state = resolve_job_state()
    project_root = os.getcwd()
    checks = {
        "job-db": state.get("db_path", ""),
        "claude-stats": os.environ.get("AGYKIT_DASH_STATS")
        or os.path.expanduser("~/.claude/stats-cache.json"),
        "claude-brain": os.path.join(
            os.environ.get("AGYKIT_DASH_BRAIN")
            or os.path.expanduser("~/.gemini/antigravity-cli/brain"),
            "*",
            ".system_generated",
            "logs",
            "transcript_full.jsonl",
        ),
        "claude-history": os.path.expanduser("~/.claude/history.jsonl"),
        "codex-history": os.environ.get("AGYKIT_DASH_CODEX_HISTORY")
        or os.path.expanduser("~/.codex/history.jsonl"),
        "codex-sessions": os.environ.get("AGYKIT_DASH_CODEX_SESSION_INDEX")
        or os.path.expanduser("~/.codex/session_index.jsonl"),
        "codex-state": os.environ.get("AGYKIT_DASH_CODEX_STATE")
        or os.path.expanduser("~/.codex/state_5.sqlite"),
        "quota-cache": os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json"),
        "statusline": os.path.expanduser(
            "~/.gemini/antigravity-cli/statusline-latest.json"
        ),
        "project-config": os.path.join(project_root, ".agykit.conf"),
        "project-system-claude": os.path.join(project_root, "CLAUDE_AGY_SYSTEM.md"),
        "project-system-codex": os.path.join(project_root, "CODEX_AGY_SYSTEM.md"),
        "project-system-opencode": os.path.join(project_root, "OPENCODE_AGY_SYSTEM.md"),
    }
    for key, path in checks.items():
        if key.endswith("-brain"):
            mtime = _newest_glob(path)
        else:
            mtime = _get_mtime(path)
        prev = _MTIME_CACHE.get(key, 0.0)
        if mtime > prev:
            changes[key] = mtime
        _MTIME_CACHE[key] = mtime

    # Map source keys to event types
    event_map = {}
    for k in changes:
        if k == "job-db":
            event_map["job"] = changes[k]
            event_map["recommendation"] = changes[k]
            event_map["forecast"] = changes[k]
            event_map["agent-matrix"] = changes[k]
        elif k.startswith("project-"):
            event_map["health"] = changes[k]
            event_map["recommendation"] = changes[k]
        if k.startswith("claude-"):
            event_map["claude"] = changes[k]
            event_map["agent-matrix"] = changes[k]
        elif k.startswith("codex-"):
            event_map["codex"] = changes[k]
            event_map["agent-matrix"] = changes[k]
        elif k == "quota-cache":
            event_map["quota"] = changes[k]
            event_map["forecast"] = changes[k]
            event_map["recommendation"] = changes[k]
            event_map["health"] = changes[k]
        elif k == "statusline":
            event_map["statusline"] = changes[k]
            event_map["health"] = changes[k]
            event_map["recommendation"] = changes[k]
    return event_map


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress server request logging for cleaner test output
        pass

    _WEB_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"
    )
    _STATIC = {
        "/style.css": "text/css",
        "/app.js": "application/javascript",
    }

    prefix = ""

    def _strip_prefix(self, raw_path):
        if not self.prefix:
            return raw_path
        if raw_path == self.prefix.rstrip("/"):
            self.send_response(302)
            self.send_header("Location", self.prefix + "/")
            self.end_headers()
            return None
        if raw_path == self.prefix + "/":
            return "/"
        if not raw_path.startswith(self.prefix + "/"):
            self.send_error(404, "Not Found")
            return None
        return "/" + raw_path[len(self.prefix) :].lstrip("/")

    def do_GET(self):
        from urllib.parse import urlparse

        parsed = urlparse(self.path)
        stripped = self._strip_prefix(parsed.path)
        if stripped is None:
            return
        path = stripped
        query = parse_qs(parsed.query)

        if path == "/":
            self.serve_index()
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path in self._STATIC:
            self.serve_static(path[1:], self._STATIC[path])
        elif path == "/api/data":
            self.serve_api(parsed.query)
        elif path == "/api/quota":
            self.serve_quota()
        elif path == "/api/statusline":
            self.serve_json(collectors.agy_statusline_snapshot())
        elif path == "/api/last-session":
            self.serve_json(collectors.agy_last_session())
        elif path == "/api/claude-quota":
            self.serve_json(collectors.claude_quota())
        elif path == "/api/agy-refresh-accounts":
            self.serve_json(collectors.agy_refresh_all_accounts())
        elif path == "/api/active-account":
            self.serve_json(collectors.agy_active_account())
        elif path == "/api/agy-model-quota":
            force = "refresh" in parsed.query
            self.serve_json(collectors.agy_model_quota_cached(force=force))
        elif path == "/api/ops-log":
            limit = 50
            if "limit=" in parsed.query:
                try:
                    limit = int(parsed.query.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self.serve_json(collectors.ops_log(limit=limit))
        elif path == "/api/rtk-stats":
            self.serve_json(collectors.rtk_stats())
        elif path == "/api/job-stats":
            self.serve_json(collectors.job_stats())
        elif path == "/api/cc-activity":
            limit = 20
            if "limit=" in parsed.query:
                try:
                    limit = int(parsed.query.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self.serve_json(collectors.cc_activity(limit=limit))
        elif path == "/api/omniroute-series":
            rng = "all"
            if "range=" in parsed.query:
                rng = parsed.query.split("range=")[1].split("&")[0]
            self.serve_json(collectors.omniroute_series(rng))
        elif path == "/api/omniroute-summary":
            self.serve_json(collectors.omniroute_summary())
        elif path == "/api/codex-status":
            self.serve_json(collectors.codex_status())
        elif path == "/api/codex-usage":
            limit = 20
            if "limit=" in parsed.query:
                try:
                    limit = int(parsed.query.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self.serve_json(collectors.codex_usage(limit=limit))
        elif path == "/api/activity-feed":
            limit = 25
            if "limit=" in parsed.query:
                try:
                    limit = int(parsed.query.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self.serve_json(collectors.activity_feed(limit=limit))
        elif path == "/api/quota-alerts":
            from dashboard import alerts as _alerts

            threshold = int(os.environ.get("AGYKIT_QUOTA_ALERT_PCT", "15"))
            self.serve_json(_alerts.check_quota_alerts(threshold, channels=["log"]))
        elif path.startswith("/api/jobs/"):
            if path.endswith("/timeline"):
                job_id = path[len("/api/jobs/") : -len("/timeline")]
                limit = int(query.get("limit", [100])[0] or 100)
                self.serve_json(collectors.job_timeline(job_id=job_id, limit=limit))
            else:
                job_id = path[len("/api/jobs/") :]
                snap = collectors.job_snapshot(job_id)
                if snap is None:
                    self.send_json_error("Job not found", 404)
                else:
                    events = collectors.job_events(job_id, limit=100)
                    self.serve_json({"snapshot": snap, "events": events})
        elif path == "/api/jobs":
            limit = 20
            if "limit=" in parsed.query:
                try:
                    limit = int(parsed.query.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self.serve_json({"jobs": collectors.job_list(limit=limit)})
        elif path == "/api/active-job":
            jobs = collectors.job_list(limit=1)
            active = None
            if jobs:
                j = jobs[0]
                if j.get("status") in (
                    "starting",
                    "running",
                    "verifying",
                    "rotating",
                    "rolling_back",
                ):
                    events = collectors.job_events(j["job_id"], limit=10)
                    active = {"snapshot": j, "events": events}
                elif j.get("status") == "succeeded" and j.get("diff_output"):
                    events = collectors.job_events(j["job_id"], limit=10)
                    active = {"snapshot": j, "events": events, "completed": True}
            self.serve_json({"active": active})
        elif path == "/api/health":
            scope = query.get("scope", ["all"])[0]
            fixable = query.get("fixable", ["false"])[0].lower() in ("1", "true", "yes")
            project_dir = query.get("project", [os.getcwd()])[0]
            self.serve_json(
                collectors.health_status(
                    project_dir=project_dir,
                    scope=scope,
                    fixable=fixable,
                )
            )
        elif path == "/api/active-job/timeline":
            limit = int(query.get("limit", [100])[0] or 100)
            self.serve_json(collectors.job_timeline(limit=limit))
        elif path == "/api/recommendation":
            mode = query.get("mode", ["balanced"])[0]
            project_dir = query.get("project", [os.getcwd()])[0]
            self.serve_json(
                collectors.recommended_account_model(mode=mode, project_dir=project_dir)
            )
        elif path == "/api/quota-forecast":
            window = query.get("window", ["24h"])[0]
            strategy = query.get("strategy", ["hybrid"])[0]
            self.serve_json(collectors.quota_forecast(window=window, strategy=strategy))
        elif path == "/api/agent-matrix":
            range_key = query.get("range", ["7d"])[0]
            self.serve_json(collectors.agent_performance_matrix(range_key=range_key))
        elif path == "/api/version":
            self.serve_json({"ok": True, "version": _read_agykit_version(), "source": "agykit"})
        elif path == "/events":
            self.serve_events()
        else:
            self.send_error(404, "Not Found")

    def serve_static(self, filename, content_type):
        file_path = os.path.join(self._WEB_DIR, filename)
        if not os.path.isfile(file_path):
            self.send_error(404, f"{filename} not found")
            return
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except Exception as e:
            self.send_error(500, f"Error reading {filename}: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_index(self):
        index_path = os.path.join(self._WEB_DIR, "index.html")
        if not os.path.isfile(index_path):
            self.send_error(500, "index.html not found")
            return

        try:
            with open(index_path, "rb") as f:
                content = f.read()
        except Exception as e:
            self.send_error(500, f"Error reading index.html: {e}")
            return

        if self.prefix:
            script = (
                f"<script>window.AGYKIT_BASE_PATH={json.dumps(self.prefix)};</script>"
            ).encode()
            content = content.replace(b"<script src=", script + b"<script src=")

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_api(self, query_string):
        from urllib.parse import parse_qs

        query = parse_qs(query_string)

        sources = query.get("source", [])
        if not sources:
            self.send_json_error("Missing source parameter", 400)
            return
        source = sources[0]

        if source not in ("claude", "agy", "omniroute"):
            self.send_json_error(f"Invalid source parameter: {source}", 400)
            return

        ranges = query.get("range", [])
        range_key = ranges[0] if ranges else "all"
        if range_key not in ("7d", "30d", "all"):
            range_key = "all"

        try:
            if source == "claude":
                stats_path = os.environ.get("AGYKIT_DASH_STATS")
                data = collectors.claude_series(range_key, stats_path=stats_path)
            elif source == "omniroute":
                data = collectors.omniroute_series(range_key)
            else:
                brain_dir = os.environ.get("AGYKIT_DASH_BRAIN")
                data = collectors.agy_series(range_key, brain_dir=brain_dir)
        except Exception as e:
            self.send_json_error(f"Collector error: {e}", 500)
            return

        try:
            body = json.dumps(data).encode("utf-8")
        except Exception as e:
            self.send_json_error(f"JSON serialization error: {e}", 500)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse(self, event_type, data="refresh"):
        try:
            msg = f"event: {event_type}\ndata: {data}\n\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    def serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        import time

        try:
            self._write_sse("meta", json.dumps({"state": "connected"}))
        except (BrokenPipeError, ConnectionResetError):
            return

        try:
            while True:
                time.sleep(5)
                changes = _check_mtimes()
                if not changes:
                    continue
                for event_type in changes:
                    self._write_sse(event_type)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            return

    def serve_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_quota(self):
        log_dir = os.environ.get("AGYKIT_DASH_LOG_DIR")
        try:
            self.serve_json(collectors.agy_quota_status(log_dir=log_dir))
        except Exception as e:
            self.send_json_error(f"Quota collector error: {e}", 500)

    def send_json_error(self, message, status_code):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("Must bind to 127.0.0.1 only")
    return ThreadingHTTPServer((host, port), DashboardHandler)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="agykit Quota Dashboard")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8787, help="Port to bind to (default: 8787)"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Do not open the browser automatically"
    )
    parser.add_argument(
        "--prefix", default="", help="URL path prefix for reverse proxy (e.g. /agykit)"
    )
    args = parser.parse_args()

    DashboardHandler.prefix = args.prefix.rstrip("/") if args.prefix else ""
    server = make_server(args.host, args.port)
    url = f"http://{args.host}:{args.port}{args.prefix}"
    print(f"agykit Dashboard running at: {url}")

    if not args.no_open:
        import webbrowser

        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
