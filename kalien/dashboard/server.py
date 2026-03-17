"""Web server for the Kalien Farmer dashboard."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from kalien.api_client import KalienAPI
from kalien.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ENGINE_SEARCH_PATHS,
    PROJECT_ROOT,
    RunnerPaths,
    ensure_data_dir,
)
from kalien.dashboard.api_builders import (
    build_api_queue,
    build_api_seeds,
    build_api_stats,
    build_api_status,
    build_api_tapes,
    build_setup_status,
)
from kalien.dashboard.controls import (
    action_add_seed,
    action_get_runner_status,
    action_pause,
    action_resume,
    action_start,
    action_stop,
    is_runner_alive,
)
from kalien.db import Database
from kalien.settings import load_settings, save_settings


# ── HTML page (loaded once at import time) ────────────────────────────
_HTML_PAGE_PATH = Path(__file__).resolve().parent / "page.html"


def _load_html() -> str:
    return _HTML_PAGE_PATH.read_text(encoding="utf-8")


def _read_log_tail(log_path: Path, lines: int = 100) -> dict[str, Any]:
    """Read the last N lines of the runner log."""
    try:
        if log_path.exists():
            text = log_path.read_text(errors="replace")
            all_lines = text.strip().split("\n")
            return {"lines": all_lines[-lines:], "total": len(all_lines)}
    except Exception:
        pass
    return {"lines": [], "total": 0}


# ── Dashboard State ───────────────────────────────────────────────────
class DashboardState:
    """Holds all mutable state shared across the dashboard threads."""

    def __init__(
        self,
        paths: RunnerPaths,
        api: KalienAPI,
        engine_search_paths: list[Path],
        project_root: Path,
    ) -> None:
        self.paths = paths
        self.api = api
        self.db = Database(paths.db)
        self.engine_search_paths = engine_search_paths
        self.project_root = project_root
        self.lock = threading.Lock()
        self.runner_proc: Optional[subprocess.Popen[bytes]] = None


# ── HTTP Handler ──────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    """Routes GET/POST requests to the appropriate builder or action."""

    # Set by the server factory — avoids module-level globals
    dashboard_state: DashboardState
    html_page: str

    def log_message(self, format: str, *args: Any) -> None:
        # Silence default request logging
        pass

    def do_GET(self) -> None:
        st = self.dashboard_state
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(self.html_page.encode())
        elif self.path == "/api/seeds":
            self._json(
                build_api_seeds(st.db, st.api, st.paths.state, st.paths.queue)
            )
        elif self.path == "/api/queue":
            self._json(build_api_queue(st.paths.queue, st.api, st.paths.settings))
        elif self.path == "/api/status":
            self._json(build_api_status(st.paths.state, st.api, st.paths.queue))
        elif self.path == "/api/stats":
            self._json(build_api_stats(st.db))
        elif self.path == "/api/runner":
            self._json(action_get_runner_status(st))
        elif self.path == "/api/settings":
            self._json(load_settings(st.paths.settings))
        elif self.path == "/api/tapes":
            self._json(build_api_tapes(st.paths.base))
        elif self.path == "/api/proofs":
            seeds = st.db.read_seeds()
            self._json(st.api.get_all_proofs(seeds))
        elif self.path == "/api/setup":
            self._json(
                build_setup_status(
                    st.engine_search_paths,
                    st.paths.settings,
                    st.paths.config,
                )
            )
        elif self.path == "/api/log":
            self._json(_read_log_tail(st.paths.log))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        st = self.dashboard_state
        length = int(self.headers.get("Content-Length", 0))
        body: dict[str, Any] = (
            json.loads(self.rfile.read(length)) if length else {}
        )
        actions: dict[str, Any] = {
            "/api/start": lambda: action_start(st),
            "/api/stop": lambda: action_stop(st),
            "/api/pause": lambda: action_pause(st),
            "/api/resume": lambda: action_resume(st),
            "/api/add_seed": lambda: action_add_seed(st, body),
            "/api/settings": lambda: save_settings(st.paths.settings, body),
        }
        handler = actions.get(self.path)
        if handler:
            self._json(handler())
        else:
            self.send_error(404)

    def _json(self, data: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


# ── Main ──────────────────────────────────────────────────────────────
def main() -> None:
    """Entry point for the dashboard CLI."""
    parser = argparse.ArgumentParser(
        description="Kalien Farmer — beam search pipeline with web dashboard"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST}; use 0.0.0.0 to expose to network)",
    )
    parser.add_argument(
        "--dir", type=str, help="Data directory (default: ./tapes)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    args = parser.parse_args()

    base = Path(args.dir) if args.dir else PROJECT_ROOT / "tapes"
    ensure_data_dir(base)
    paths = RunnerPaths.from_base(base)

    api = KalienAPI()

    dashboard_state = DashboardState(
        paths=paths,
        api=api,
        engine_search_paths=ENGINE_SEARCH_PATHS,
        project_root=PROJECT_ROOT,
    )

    # Load HTML
    html_page = _load_html()

    # Inject state into the handler class
    Handler.dashboard_state = dashboard_state
    Handler.html_page = html_page

    # Seed-refresh background thread
    def _refresh_loop() -> None:
        while True:
            api.refresh_current_seed()
            time.sleep(60)

    refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    refresh_thread.start()
    api.refresh_current_seed()

    url = f"http://localhost:{args.port}"
    print(f"\n  \u2554{'=' * 42}\u2557")
    print(f"  \u2551  KALIEN FARMER                            \u2551")
    print(f"  \u2551  {url:<39s} \u2551")
    print(f"  \u255a{'=' * 42}\u255d\n")

    if not args.no_browser:

        def open_browser() -> None:
            if "microsoft" in platform.uname().release.lower():
                try:
                    subprocess.Popen(
                        ["cmd.exe", "/c", f"start {url}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception:
                    pass
            webbrowser.open(url)

        threading.Timer(1.0, open_browser).start()

    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        with dashboard_state.lock:
            if (
                dashboard_state.runner_proc
                and dashboard_state.runner_proc.poll() is None
            ):
                print("Stopping runner...")
                dashboard_state.runner_proc.terminate()
                try:
                    dashboard_state.runner_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    dashboard_state.runner_proc.kill()
                print("Runner stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
