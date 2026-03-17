"""State file and results management for the runner."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from kalien.config import now_iso


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically write *state* to *path* via a temp-file rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)


def load_state(path: Path) -> Optional[dict[str, Any]]:
    """Load a previously saved state dict, or return ``None``."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def clear_state(path: Path) -> None:
    """Remove the state file (if it exists)."""
    path.unlink(missing_ok=True)


def record_result(results_path: Path, state: dict[str, Any]) -> None:
    """Append a one-line summary of *state* to the results TSV."""
    if not results_path.exists():
        with open(results_path, "w") as f:
            f.write("timestamp\tseed\tseed_id\tbest_score\tbest_salt\tsalts\telapsed\tbeam\n")
    ts = now_iso()
    total = state["salt_end"] - state.get("salt_start_orig", 0)
    elapsed = state.get("elapsed", 0)
    with open(results_path, "a") as f:
        f.write(
            f"{ts}\t{state['seed']}\t{state['seed_id']}\t{state['best_score']}\t"
            f"{state['best_salt']}\t{total}\t{elapsed}s\tw{state['beam']}\n"
        )
