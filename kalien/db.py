"""SQLite database access for seed tracking."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from kalien.config import now_iso


class Database:
    """Thin wrapper around the ``kalien.db`` SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    # ── Connection ────────────────────────────────────────────────
    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield an auto-committing connection; closes on exit."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Schema management ─────────────────────────────────────────
    def init_schema(self) -> None:
        """Create the ``seeds`` table if it does not exist."""
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seeds (
                    seed_hex TEXT PRIMARY KEY,
                    seed_id INTEGER UNIQUE NOT NULL,
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
                    updated_at TEXT NOT NULL
                )
            """)

    def ensure_schema(self) -> None:
        """Add columns that may be missing in older DB schemas (migration)."""
        with self.connect() as conn:
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(seeds)").fetchall()
            }
            migrations: list[tuple[str, str]] = [
                ("submitted_score", "INTEGER DEFAULT 0"),
                ("submitted_job_id", "TEXT DEFAULT ''"),
            ]
            for col_name, col_def in migrations:
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE seeds ADD COLUMN {col_name} {col_def}")

    # ── CRUD ──────────────────────────────────────────────────────
    def record_seed(self, seed_hex: str, seed_id: int) -> None:
        """Insert a new seed row (ignored if already present)."""
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seeds (seed_hex, seed_id, updated_at) VALUES (?,?,?)",
                (seed_hex, seed_id, ts),
            )

    def update_qualify(
        self, seed_hex: str, score: int, salt: str, elapsed: int
    ) -> None:
        """Update the qualify columns if *score* is a new best."""
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """UPDATE seeds SET qualify_score=?, qualify_salt=?, qualify_elapsed=?, updated_at=?
                   WHERE seed_hex=? AND ? > qualify_score""",
                (score, salt, elapsed, ts, seed_hex, score),
            )

    def update_push(
        self,
        seed_hex: str,
        status: str,
        *,
        beam: int = 0,
        score: int = 0,
        salt: str = "",
        salts_done: int = 0,
        salts_total: int = 0,
        elapsed: int = 0,
    ) -> None:
        """Update push-phase columns, keeping the best score seen so far."""
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """UPDATE seeds SET push_status=?, push_beam=?, push_score=MAX(push_score,?),
                   push_salt=CASE WHEN ?>push_score THEN ? ELSE push_salt END,
                   push_salts_done=?, push_salts_total=?, push_elapsed=?, updated_at=?
                   WHERE seed_hex=?""",
                (status, beam, score, score, salt, salts_done, salts_total, elapsed, ts, seed_hex),
            )

    def update_submitted(
        self, seed_hex: str, score: int, job_id: str = ""
    ) -> None:
        """Record a successful tape submission."""
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE seeds SET submitted_score=?, submitted_job_id=?, updated_at=? WHERE seed_hex=?",
                (score, job_id, ts, seed_hex),
            )

    # ── Reads ─────────────────────────────────────────────────────
    def read_seeds(self) -> list[dict[str, Any]]:
        """Return all seed rows as a list of dicts, newest first."""
        try:
            if not self.db_path.exists():
                return []
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            self.ensure_schema()
            rows = conn.execute(
                "SELECT * FROM seeds ORDER BY seed_id DESC"
            ).fetchall()
            result = [dict(r) for r in rows]
            conn.close()
            return result
        except Exception:
            return []
