"""Queue management with cross-platform file locking."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from kalien.config import IS_WINDOWS


# ── Data class ────────────────────────────────────────────────────────
@dataclass
class QueueEntry:
    """A single parsed queue entry."""

    seed: str
    seed_id: int = 0
    salts: Optional[int] = None
    salt_start: int = 0
    beam: Optional[int] = None


# ── File locking ──────────────────────────────────────────────────────
@contextmanager
def queue_lock(queue_path: Path) -> Generator[None, None, None]:
    """Cross-platform file lock for queue operations.

    Uses ``fcntl`` on Unix and ``msvcrt`` on Windows.  The lock file is
    shared between the runner and dashboard processes.
    """
    lock_path = queue_path.with_suffix(".lock")
    lock_fh = open(lock_path, "w")
    try:
        if IS_WINDOWS:
            import msvcrt
            # Retry with backoff — msvcrt.locking raises on contention
            for _attempt in range(50):
                try:
                    msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except IOError:
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if IS_WINDOWS:
                import msvcrt
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
        except Exception:
            pass
        lock_fh.close()


# ── Parsing ───────────────────────────────────────────────────────────
def parse_queue_entry(line: str) -> Optional[QueueEntry]:
    """Parse a colon-delimited queue line into a :class:`QueueEntry`.

    Returns ``None`` if the line is malformed.

    Format: ``SEED_HEX:SEED_ID[:SALTS[:SALT_START[:BEAM]]]``
    """
    parts = line.strip().split(":")
    if len(parts) < 2:
        return None
    seed = parts[0].upper()
    if not seed or not all(c in "0123456789ABCDEF" for c in seed):
        return None
    try:
        sid = int(parts[1])
        salts = int(parts[2]) if len(parts) > 2 and parts[2] != seed else None
        salt_start = int(parts[3]) if len(parts) > 3 else 0
        beam = int(parts[4]) if len(parts) > 4 else None
    except (ValueError, IndexError):
        return None
    return QueueEntry(seed=seed, seed_id=sid, salts=salts, salt_start=salt_start, beam=beam)


# ── Queue operations ─────────────────────────────────────────────────
def pop_queue(queue_path: Path, qualify_beam: int) -> Optional[str]:
    """Pop the next entry from the queue file.

    Prioritises entries whose beam width exceeds *qualify_beam*,
    indicating they are push runs that should take precedence.
    Uses file locking to prevent race conditions with the dashboard.
    """
    with queue_lock(queue_path):
        if not queue_path.exists():
            return None
        lines = [l.strip() for l in queue_path.read_text().strip().split("\n") if l.strip()]
        if not lines:
            return None

        chosen_idx = 0
        for i, line in enumerate(lines):
            parts = line.split(":")
            if len(parts) >= 5:
                try:
                    if int(parts[4]) > qualify_beam:
                        chosen_idx = i
                        break
                except ValueError:
                    pass

        chosen = lines.pop(chosen_idx)
        queue_path.write_text("\n".join(lines) + "\n" if lines else "")
        return chosen


def push_queue_front(queue_path: Path, entry: str) -> None:
    """Insert an entry at the front of the queue file."""
    with queue_lock(queue_path):
        lines: list[str] = []
        if queue_path.exists():
            lines = [l.strip() for l in queue_path.read_text().strip().split("\n") if l.strip()]
        lines.insert(0, entry)
        queue_path.write_text("\n".join(lines) + "\n")


def read_queue(queue_path: Path) -> list[str]:
    """Return all non-empty lines from the queue file."""
    try:
        if queue_path.exists():
            lines = queue_path.read_text().strip().split("\n")
            return [l.strip() for l in lines if l.strip()]
    except Exception:
        pass
    return []
