import os
import sys
import json
import glob
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Allow importing dashboard modules when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dashboard import collectors


def get_current_mtime_state():
    stats_path = os.environ.get("AGYKIT_DASH_STATS") or os.path.expanduser(
        "~/.claude/stats-cache.json"
    )
    brain_dir = os.environ.get("AGYKIT_DASH_BRAIN") or os.path.expanduser(
        "~/.gemini/antigravity-cli/brain"
    )

    stats_mtime = 0.0
    if os.path.isfile(stats_path):
        try:
            stats_mtime = os.path.getmtime(stats_path)
        except Exception:
            pass

    newest_brain_mtime = 0.0
    if os.path.isdir(brain_dir):
        try:
            pattern = os.path.join(
                brain_dir, "*", ".system_generated", "logs", "transcript_full.jsonl"
            )
            files = glob.glob(pattern)
            if files:
                newest_brain_mtime = max(os.path.getmtime(f) for f in files)
        except Exception:
            pass

    return stats_mtime, newest_brain_mtime


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress server request logging for cleaner test output
        pass

    def do_GET(self):
        from urllib.parse import urlparse

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.serve_index()
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
        elif path == "/events":
            self.serve_events()
        else:
            self.send_error(404, "Not Found")

    def serve_index(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        index_path = os.path.join(current_dir, "index.html")
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

        if source not in ("claude", "agy"):
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

    def serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self.wfile.write(b"data: hello\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

        last_state = get_current_mtime_state()
        import time

        try:
            while True:
                time.sleep(3)
                current_state = get_current_mtime_state()
                if current_state != last_state:
                    self.wfile.write(b"data: refresh\n\n")
                    self.wfile.flush()
                    last_state = current_state
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
