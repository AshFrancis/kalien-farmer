"""API response builders for the dashboard HTTP endpoints."""
from __future__ import annotations

import json
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from kalien.api_client import KalienAPI
from kalien.config import ENGINE_SEARCH_PATHS, RunnerPaths
from kalien.db import Database
from kalien.queue import read_queue
from kalien.settings import DEFAULT_SETTINGS, is_valid_claimant, load_settings
from kalien.state import load_state


def _detect_os() -> str:
    """Return a human-readable OS name."""
    s = platform.system()
    if s == "Darwin":
        return "macOS"
    if s == "Windows":
        return "Windows"
    return "Linux"


def build_api_seeds(
    db: Database,
    api: KalienAPI,
    state_path: Path,
    queue_path: Path,
) -> list[dict[str, Any]]:
    """Build the ``/api/seeds`` response payload."""
    seeds = db.read_seeds()
    csid = api.current_seed_id
    state = load_state(state_path) or {}
    queue = read_queue(queue_path)

    queue_pos: dict[str, int] = {}
    for i, line in enumerate(queue):
        parts = line.split(":")
        if parts:
            queue_pos.setdefault(parts[0].upper(), i + 1)

    result: list[dict[str, Any]] = []
    for s in seeds:
        sid: int = s["seed_id"]
        age_min = (csid - sid) * 10 if csid else 0
        rem_min = 24 * 60 - age_min
        is_running = (
            state.get("seed", "").upper() == s["seed_hex"].upper()
            and bool(state.get("phase"))
        )

        entry: dict[str, Any] = {
            "seed": s["seed_hex"],
            "seed_id": sid,
            "age_min": age_min,
            "remaining_min": rem_min,
            "qualify_score": s["qualify_score"],
            "push_status": s["push_status"],
            "push_beam": s["push_beam"],
            "push_score": s["push_score"],
            "push_salts_done": s["push_salts_done"],
            "push_salts_total": s["push_salts_total"],
            "queue_pos": queue_pos.get(s["seed_hex"].upper()),
            "is_running": is_running,
            "submitted_score": s.get("submitted_score", 0),
            "submitted_job_id": s.get("submitted_job_id", ""),
        }
        if is_running:
            entry.update(
                {
                    "run_phase": state.get("phase"),
                    "run_beam": state.get("beam"),
                    "run_salt": state.get("salt_current"),
                    "run_salt_end": state.get("salt_end"),
                    "run_best": state.get("best_score"),
                }
            )
        result.append(entry)
    return result


def build_api_queue(
    queue_path: Path,
    api: KalienAPI,
    settings_path: Path,
) -> list[dict[str, Any]]:
    """Build the ``/api/queue`` response payload."""
    queue = read_queue(queue_path)
    csid = api.current_seed_id
    settings = load_settings(settings_path)
    qualify_beam: int = settings.get("qualify_beam", DEFAULT_SETTINGS["qualify_beam"])
    push_beam: int = settings.get("push_beam", DEFAULT_SETTINGS["push_beam"])

    result: list[dict[str, Any]] = []
    for i, line in enumerate(queue):
        parts = line.split(":")
        seed = parts[0]
        sid = int(parts[1]) if len(parts) > 1 else 0
        salts = parts[2] if len(parts) > 2 and parts[2] != seed else None
        beam = int(parts[4]) if len(parts) > 4 else None
        age_min = (csid - sid) * 10 if csid else 0
        rem_min = 24 * 60 - age_min
        run_type = "push" if salts else "qualify"
        result.append(
            {
                "pos": i + 1,
                "seed": seed,
                "seed_id": sid,
                "type": run_type,
                "beam": beam or (qualify_beam if run_type == "qualify" else push_beam),
                "salts": int(salts) if salts else (1 if run_type == "qualify" else 30),
                "remaining_min": rem_min,
            }
        )
    return result


def build_api_status(
    state_path: Path,
    status_path: Path,
    api: KalienAPI,
    queue_path: Path,
) -> dict[str, Any]:
    """Build the ``/api/status`` response payload."""
    state = load_state(state_path) or {}
    # Parse live frame progress from status.txt
    progress: dict[str, Any] = {}
    try:
        if status_path.exists():
            line = status_path.read_text().strip()
            import re
            m = re.search(r"frame=(\d+)/(\d+)", line)
            if m:
                progress["frame"] = int(m.group(1))
                progress["total_frames"] = int(m.group(2))
            m = re.search(r"score=(\d+)", line)
            if m:
                progress["live_score"] = int(m.group(1))
            m = re.search(r"salt=(\d+)/(\d+)", line)
            if m:
                progress["salt"] = int(m.group(1))
                progress["salt_total"] = int(m.group(2))
    except Exception:
        pass
    return {
        "state": state,
        "progress": progress,
        "connected": api.is_connected,
        "current_seed_id": api.current_seed_id,
        "queue_length": len(read_queue(queue_path)),
    }


def build_api_stats(db: Database) -> dict[str, Any]:
    """Build the ``/api/stats`` response payload."""
    seeds = db.read_seeds()
    scores: list[dict[str, Any]] = []
    for s in reversed(seeds):
        best = max(s["qualify_score"] or 0, s["push_score"] or 0)
        if best > 0:
            scores.append(
                {
                    "seed_id": s["seed_id"],
                    "seed": s["seed_hex"],
                    "qualify": s["qualify_score"] or 0,
                    "push": s["push_score"] or 0,
                    "best": best,
                }
            )
    return {"scores": scores[-100:]}


def build_api_tapes(base_path: Path) -> list[dict[str, Any]]:
    """Build the ``/api/tapes`` response payload.

    Scans for seed directories — supports both legacy ``<hex>_v9``
    naming and the plain ``<hex>`` naming.
    """
    tapes: list[dict[str, Any]] = []
    for d in sorted(base_path.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        dirname = d.name.upper()
        if dirname.endswith("_V9"):
            seed = dirname[:-3]
        elif re.fullmatch(r"[0-9A-F]{8}", dirname):
            seed = dirname
        else:
            continue
        for t in sorted(
            d.glob("*.tape"), key=lambda f: f.stat().st_mtime, reverse=True
        ):
            m = re.search(r"_(\d+)_(\d+)\.tape$", t.name)
            if m:
                salt, score = int(m.group(1)), int(m.group(2))
                tapes.append(
                    {
                        "seed": seed,
                        "salt": salt,
                        "score": score,
                        "file": str(t.name),
                        "path": str(t),
                        "size": t.stat().st_size,
                        "time": datetime.fromtimestamp(
                            t.stat().st_mtime
                        ).strftime("%Y-%m-%d %H:%M"),
                    }
                )
    return tapes[:200]


def _load_benchmark(config_path: Path) -> dict[str, Any]:
    """Load benchmark.json if it exists."""
    try:
        if config_path.exists():
            import json
            return json.loads(config_path.read_text())
    except Exception:
        pass
    return {}


def build_setup_status(
    engine_search_paths: list[Path],
    settings_path: Path,
    benchmark_path: Path,
) -> dict[str, Any]:
    """Build the ``/api/setup`` response payload."""
    from kalien.config import find_engine

    engine = find_engine(engine_search_paths)
    settings = load_settings(settings_path)
    claimant = settings.get("claimant", "")
    settings_configured = is_valid_claimant(claimant)
    benchmark_done = benchmark_path.exists()
    benchmark = _load_benchmark(benchmark_path)
    return {
        "engine_found": engine is not None,
        "engine_path": str(engine) if engine else None,
        "settings_configured": settings_configured,
        "claimant": claimant,
        "benchmark_done": benchmark_done,
        "benchmark": benchmark,
        "os": _detect_os(),
        "python_version": platform.python_version(),
    }
