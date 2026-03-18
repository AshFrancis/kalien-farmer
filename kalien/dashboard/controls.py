"""Runner lifecycle actions invoked from the dashboard UI."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any

from kalien.config import IS_WINDOWS, find_engine, ENGINE_SEARCH_PATHS, ensure_data_dir
from kalien.queue import queue_lock, read_queue
from kalien.settings import is_valid_claimant, load_settings, DEFAULT_SETTINGS

if TYPE_CHECKING:
    from kalien.dashboard.server import DashboardState

# When running as a PyInstaller bundle, we can't spawn a separate Python
# process. Instead we run the runner in a background thread.
_runner_thread: threading.Thread | None = None
_runner_thread_stopping = threading.Event()


def find_orphan_pid() -> str | None:
    """Find orphaned ``runner.py`` processes not managed by the dashboard."""
    try:
        if IS_WINDOWS:
            r = subprocess.run(
                [
                    "wmic", "process", "where",
                    "commandline like '%runner.py%' and name like '%python%'",
                    "get", "processid",
                ],
                capture_output=True, text=True, timeout=5,
            )
            pids = [p.strip() for p in r.stdout.split() if p.strip().isdigit()]
        else:
            r = subprocess.run(
                ["pgrep", "-f", "runner.py"],
                capture_output=True, text=True, timeout=5,
            )
            pids = [p for p in r.stdout.strip().split() if p]
        pids = [p for p in pids if int(p) != os.getpid()]
        return pids[0] if pids else None
    except Exception:
        return None


def is_runner_alive(state: DashboardState) -> str | None:
    """Return the PID string of a live runner, or ``None``."""
    global _runner_thread
    # Check in-process thread (PyInstaller mode)
    if _runner_thread and _runner_thread.is_alive():
        return "thread"
    # Check subprocess
    with state.lock:
        if state.runner_proc and state.runner_proc.poll() is None:
            return str(state.runner_proc.pid)
        state.runner_proc = None
    return find_orphan_pid()


def _run_in_thread(state: DashboardState, engine_path: str) -> None:
    """Entry point for the runner when running in a background thread."""
    from kalien.runner import main as runner_main
    sys.argv = [
        "runner",
        "--dir", str(state.paths.base),
        "--binary", engine_path,
    ]
    try:
        runner_main()
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception as e:
        import traceback
        with open(state.paths.log, "a") as f:
            f.write(f"Runner thread error: {e}\n")
            f.write(traceback.format_exc() + "\n")


def action_start(state: DashboardState) -> dict[str, Any]:
    """Start the runner (as subprocess or thread depending on environment)."""
    global _runner_thread
    engine = find_engine(state.engine_search_paths)
    if not engine:
        search = ", ".join(str(p) for p in state.engine_search_paths)
        return {
            "ok": False,
            "msg": (
                f"Engine binary not found. Searched: {search}. "
                "Build it first (see Setup tab)."
            ),
        }

    settings = load_settings(state.paths.settings)
    claimant = settings.get("claimant", "")
    if not is_valid_claimant(claimant):
        return {
            "ok": False,
            "msg": (
                "Valid Stellar address required (starts with G or C, 56 characters). "
                "Configure it in the Setup tab."
            ),
        }

    pid = is_runner_alive(state)
    if pid:
        return {"ok": False, "msg": f"Already running (PID {pid})"}

    ensure_data_dir(state.paths.base)

    if getattr(sys, 'frozen', False):
        # PyInstaller bundle: run in a thread (can't spawn separate Python)
        _runner_thread_stopping.clear()
        _runner_thread = threading.Thread(
            target=_run_in_thread,
            args=(state, str(engine)),
            daemon=True,
        )
        _runner_thread.start()
        return {"ok": True, "msg": "Started runner (in-process)"}
    else:
        # Normal: run as subprocess
        kwargs: dict[str, Any] = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        log_fh = open(state.paths.log, "a")
        try:
            runner_cmd = [
                sys.executable, "-m", "kalien.runner",
                "--dir", str(state.paths.base),
                "--binary", str(engine),
            ]
            with state.lock:
                state.runner_proc = subprocess.Popen(
                    runner_cmd,
                    cwd=str(state.project_root),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    **kwargs,
                )
            log_fh.close()
        except Exception:
            log_fh.close()
            raise
        return {"ok": True, "msg": f"Started runner (PID {state.runner_proc.pid})"}


def action_stop(state: DashboardState) -> dict[str, Any]:
    """Stop the runner (subprocess or thread)."""
    global _runner_thread
    pid = is_runner_alive(state)
    if not pid:
        return {"ok": False, "msg": "Not running"}

    if pid == "thread":
        # Thread mode: create the pause file to signal graceful stop,
        # then the thread will exit after the current salt
        state.paths.pause.touch()
        # Give it a moment, then just let it wind down
        return {"ok": True, "msg": "Stopping runner (will finish current salt)"}
    else:
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
        with state.lock:
            if state.runner_proc:
                try:
                    state.runner_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    state.runner_proc.kill()
                state.runner_proc = None
        return {"ok": True, "msg": f"Stopped runner (PID {pid})"}


def action_pause(state: DashboardState) -> dict[str, Any]:
    """Create the pause sentinel file."""
    state.paths.pause.touch()
    return {"ok": True, "msg": "Paused — runner will stop after current salt"}


def action_resume(state: DashboardState) -> dict[str, Any]:
    """Remove the pause sentinel file."""
    state.paths.pause.unlink(missing_ok=True)
    return {"ok": True, "msg": "Resumed"}


def action_add_seed(
    state: DashboardState, data: dict[str, Any]
) -> dict[str, Any]:
    """Add a seed to the front of the queue."""
    seed = data.get("seed", "").strip().upper().replace("0X", "")
    settings = load_settings(state.paths.settings)
    beam = int(data.get("beam", 0) or settings.get("push_beam", 0) or 65536)
    salts = int(data.get("salts", 30))
    if (
        not seed
        or len(seed) != 8
        or not all(c in "0123456789ABCDEF" for c in seed)
    ):
        return {"ok": False, "msg": "Invalid seed (need exactly 8 hex characters)"}
    sid = data.get("seed_id", 0)
    if not sid:
        for line in read_queue(state.paths.queue):
            parts = line.split(":")
            if parts[0].upper() == seed:
                sid = int(parts[1])
                break
    if not sid:
        return {
            "ok": False,
            "msg": "Need seed_id — not found in queue. Provide seed_id field.",
        }
    entry = f"{seed}:{sid}:{salts}:0:{beam}"
    with queue_lock(state.paths.queue):
        lines = read_queue(state.paths.queue)
        lines.insert(0, entry)
        state.paths.queue.write_text("\n".join(lines) + "\n")
    return {
        "ok": True,
        "msg": f"Added {seed} (w={beam}, {salts} salts) to front of queue",
    }


def action_remove_queue(
    state: DashboardState, data: dict[str, Any]
) -> dict[str, Any]:
    """Remove a queue entry by position (1-based)."""
    pos = int(data.get("pos", 0))
    if pos < 1:
        return {"ok": False, "msg": "Invalid position"}
    with queue_lock(state.paths.queue):
        lines = read_queue(state.paths.queue)
        if pos > len(lines):
            return {"ok": False, "msg": f"Position {pos} out of range ({len(lines)} items)"}
        removed = lines.pop(pos - 1)
        state.paths.queue.write_text("\n".join(lines) + "\n" if lines else "")
    seed = removed.split(":")[0] if removed else "?"
    return {"ok": True, "msg": f"Removed #{pos} ({seed}) from queue"}


def action_get_runner_status(state: DashboardState) -> dict[str, Any]:
    """Return whether the runner is alive/paused."""
    pid = is_runner_alive(state)
    paused = state.paths.pause.exists()
    return {"ok": True, "running": pid is not None, "paused": paused, "pid": pid}
