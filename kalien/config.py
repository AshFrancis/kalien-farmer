"""Constants, filesystem paths, platform detection, and shared helpers."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Platform detection ────────────────────────────────────────────────
IS_WINDOWS: bool = sys.platform == "win32"

_BIN_NAME: str = "kalien.exe" if IS_WINDOWS else "kalien"

# When running as a PyInstaller bundle, __file__ points to a temp extraction
# directory. Use the executable's directory for user-facing paths instead.
if getattr(sys, 'frozen', False):
    # PyInstaller bundle: use directory containing the executable
    PROJECT_ROOT: Path = Path(sys.executable).resolve().parent
    # Bundled engine is inside the executable's temp dir
    _BUNDLE_DIR: Path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    ENGINE_SEARCH_PATHS: list[Path] = [
        _BUNDLE_DIR / "engine" / _BIN_NAME,
        PROJECT_ROOT / "engine" / _BIN_NAME,
        PROJECT_ROOT / _BIN_NAME,
    ]
else:
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
    ENGINE_SEARCH_PATHS: list[Path] = [
        PROJECT_ROOT / "engine" / _BIN_NAME,
        PROJECT_ROOT / _BIN_NAME,
        Path.home() / "kalien-farmer" / "engine" / _BIN_NAME,
    ]

# ── Pipeline constants ────────────────────────────────────────────────
DEFAULT_PUSH_THRESHOLD: int = 1_190_000
MIN_REMAINING_HOURS: int = 4
MIN_REMAINING_FINISH_MINUTES: int = 30
EXPIRY_RECHECK_SALTS: int = 5
QUALIFY_SALTS: int = 1

# Push runs are time-boxed, not salt-count-limited.
# Tiers are multiples of the calibrated qualify beam.
PUSH_TIERS: list[dict] = [
    {"multiplier": 2, "hours": 3},
    {"multiplier": 4, "hours": 6},
]

HORIZON: int = 20
FRAMES: int = 36_000
BRANCHES: int = 8

# ── API / network ────────────────────────────────────────────────────
API_BASE: str = "https://kalien.xyz"
USER_AGENT: str = "kalien-farmer/2.0"

# Fixed seed used for benchmarking.  The specific value does not matter —
# it just needs to be deterministic so timing results are reproducible.
BENCHMARK_SEED: str = "DEADBEEF"

# ── Dashboard defaults ────────────────────────────────────────────────
DEFAULT_PORT: int = 8420
DEFAULT_HOST: str = "127.0.0.1"  # localhost only by default for security
REFRESH_INTERVAL: int = 3


# ── Filesystem paths ─────────────────────────────────────────────────
@dataclass
class RunnerPaths:
    """All filesystem paths used by the runner and dashboard."""

    base: Path
    db: Path
    state: Path
    queue: Path
    status: Path
    pause: Path
    results: Path
    config: Path
    log: Path
    settings: Path

    @classmethod
    def from_base(cls, base: Path) -> RunnerPaths:
        return cls(
            base=base,
            db=base / "kalien.db",
            state=base / "state.json",
            queue=base / "seed_queue.txt",
            status=base / "status.txt",
            pause=base / "pause",
            results=base / "results.tsv",
            config=base / "benchmark.json",
            log=base / "runner.log",
            settings=base / "settings.json",
        )


# ── Helpers ───────────────────────────────────────────────────────────
def find_engine(search_paths: Optional[list[Path]] = None) -> Optional[Path]:
    """Search known paths for the kalien engine binary."""
    for p in (search_paths or ENGINE_SEARCH_PATHS):
        p = p.resolve()
        if p.exists():
            return p
    return None


def now_iso() -> str:
    """Return the current local time as an ISO-ish timestamp string."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def ensure_data_dir(base: Path) -> None:
    """Create the data directory tree if it does not already exist."""
    base.mkdir(parents=True, exist_ok=True)
