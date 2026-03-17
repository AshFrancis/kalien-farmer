"""Runner lifecycle actions invoked from the dashboard UI."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from kalien.config import IS_WINDOWS, find_engine, ENGINE_SEARCH_PATHS, ensure_data_dir
from kalien.queue import queue_lock, read_queue
from kalien.settings import is_valid_claimant, load_settings, DEFAULT_SETTINGS

if TYPE_CHECKING:
    from kalien.dashboard.server import DashboardState


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
    with state.lock:
        if state.runner_proc and state.runner_proc.poll() is None:
            return str(state.runner_proc.pid)
        state.runner_proc = None
    return find_orphan_pid()


def action_start(state: DashboardState) -> dict[str, Any]:
    """Start the runner subprocess."""
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

    kwargs: dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    log_fh = open(state.paths.log, "a")
    try:
        runner_cmd = [
            sys.executable, "-m", "kalien.runner",
            "--dir", str(state.paths.base),
        ]
        if engine:
            runner_cmd += ["--binary", str(engine)]
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
    """Stop the runner subprocess."""
    pid = is_runner_alive(state)
    if not pid:
        return {"ok": False, "msg": "Not running"}
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
    beam = int(
        data.get("beam", settings.get("push_beam", DEFAULT_SETTINGS["push_beam"]))
    )
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


def action_get_runner_status(state: DashboardState) -> dict[str, Any]:
    """Return whether the runner is alive/paused."""
    pid = is_runner_alive(state)
    paused = state.paths.pause.exists()
    return {"ok": True, "running": pid is not None, "paused": paused, "pid": pid}
