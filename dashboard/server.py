import os
import sys
import json
import glob
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Always import from the repo containing this server.py — not from cwd
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)
# Invalidate any stale cached import before loading
for _k in list(sys.modules):
    if _k == "dashboard" or _k.startswith("dashboard.collectors"):
        del sys.modules[_k]
from dashboard import collectors  # noqa: E402


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
    checks = {
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
        if k.startswith("claude-"):
            event_map["claude"] = changes[k]
        elif k.startswith("codex-"):
            event_map["codex"] = changes[k]
        elif k == "quota-cache":
            event_map["quota"] = changes[k]
        elif k == "statusline":
            event_map["statusline"] = changes[k]
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

    def do_GET(self):
        from urllib.parse import urlparse

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.serve_index()
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
            self._write_sse("meta", "connected")
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
    args = parser.parse_args()

    server = make_server(args.host, args.port)
    url = f"http://{args.host}:{args.port}"
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
