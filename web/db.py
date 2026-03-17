"""Multi-user SQLite database for the web farmer.

Same schema as kalien.db but partitioned by claimant address.
Each user only sees their own seeds.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class WebDatabase:
    """Thin wrapper around SQLite with per-claimant seed tracking."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seeds (
                    claimant TEXT NOT NULL,
                    seed_hex TEXT NOT NULL,
                    seed_id INTEGER NOT NULL,
                    qualify_score INTEGER DEFAULT 0,
                    qualify_salt TEXT DEFAULT '',
                    qualify_elapsed INTEGER DEFAULT 0,
                    push_status TEXT DEFAULT 'none',
                    push_beam INTEGER DEFAULT 0,
                    push_score INTEGER DEFAULT 0,
                    push_salt TEXT DEFAULT '',
                    push_salts_done INTEGER DEFAULT 0,
                    push_salts_total INTEGER DEFAULT 0,
                    push_elapsed INTEGER DEFAULT 0,
                    submitted_score INTEGER DEFAULT 0,
                    submitted_job_id TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (claimant, seed_hex)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_seeds_claimant
                ON seeds (claimant, seed_id DESC)
            """)

    def record_seed(self, claimant: str, seed_hex: str, seed_id: int) -> None:
        ts = _now()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seeds (claimant, seed_hex, seed_id, updated_at) VALUES (?,?,?,?)",
                (claimant, seed_hex, seed_id, ts),
            )

    def update_qualify(
        self, claimant: str, seed_hex: str, score: int, salt: str, elapsed: int
    ) -> None:
        ts = _now()
        with self.connect() as conn:
            conn.execute(
                """UPDATE seeds SET qualify_score=?, qualify_salt=?, qualify_elapsed=?, updated_at=?
                   WHERE claimant=? AND seed_hex=? AND ? > qualify_score""",
                (score, salt, elapsed, ts, claimant, seed_hex, score),
            )

    def update_submitted(
        self, claimant: str, seed_hex: str, score: int, job_id: str = ""
    ) -> None:
        ts = _now()
        with self.connect() as conn:
            conn.execute(
                """UPDATE seeds SET submitted_score=?, submitted_job_id=?, updated_at=?
                   WHERE claimant=? AND seed_hex=?""",
                (score, job_id, ts, claimant, seed_hex),
            )

    def read_seeds(self, claimant: str) -> list[dict[str, Any]]:
        try:
            if not self.db_path.exists():
                return []
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM seeds WHERE claimant=? ORDER BY seed_id DESC",
                (claimant,),
            ).fetchall()
            result = [dict(r) for r in rows]
            conn.close()
            return result
        except Exception:
            return []

    def read_all_runs(self) -> list[dict[str, Any]]:
        """Return all runs across all users, newest first."""
        try:
            if not self.db_path.exists():
                return []
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT claimant, seed_hex, seed_id, qualify_score, qualify_elapsed,
                          submitted_score, submitted_job_id, updated_at
                   FROM seeds ORDER BY seed_id DESC, qualify_score DESC"""
            ).fetchall()
            result = [dict(r) for r in rows]
            conn.close()
            return result
        except Exception:
            return []

    def already_qualified(self, claimant: str, seed_hex: str) -> bool:
        try:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT qualify_score FROM seeds WHERE claimant=? AND seed_hex=?",
                    (claimant, seed_hex),
                ).fetchone()
            return row is not None and row[0] > 0
        except Exception:
            return False
