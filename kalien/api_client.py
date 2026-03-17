"""HTTP client for the kalien.xyz API."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.request import Request, urlopen

from kalien.config import API_BASE, USER_AGENT, MIN_REMAINING_FINISH_MINUTES


@dataclass
class SeedCacheEntry:
    """Cached API response for the current seed."""

    timestamp: float = 0.0
    seed_id: int = 0
    seed_hex: Optional[str] = None


class KalienAPI:
    """Stateful client for the kalien.xyz REST API.

    Caches the current seed for 60 seconds to avoid hammering the
    server.  Also provides proof-status caching for the dashboard.
    """

    def __init__(self, log_fn: Optional[Callable[[str], None]] = None) -> None:
        self._seed_cache = SeedCacheEntry()
        self._proof_cache: dict[str, dict[str, Any]] = {}
        self._proof_cache_ttl: float = 60.0
        self._proofs_result_cache: Optional[dict[str, Any]] = None
        self._proofs_result_ts: float = 0.0
        self._proofs_result_ttl: float = 60.0
        self._log_fn = log_fn or (lambda _msg: None)
        self._connected: bool = False

    # ── Properties ────────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        """Whether the last API call succeeded."""
        return self._connected

    @property
    def current_seed_id(self) -> int:
        """The most-recently observed seed ID (may be stale)."""
        return self._seed_cache.seed_id

    # ── Seed endpoints ────────────────────────────────────────────
    def get_current_seed(self) -> tuple[Optional[int], Optional[str]]:
        """Fetch the current seed from the API (cached 60 s).

        Returns ``(seed_id, seed_hex)`` or ``(None, None)`` on error.
        """
        now = time.time()
        if now - self._seed_cache.timestamp < 60:
            return self._seed_cache.seed_id or None, self._seed_cache.seed_hex
        try:
            req = Request(
                f"{API_BASE}/api/seed/current",
                headers={"User-Agent": USER_AGENT},
            )
            data = json.loads(urlopen(req, timeout=10).read())
            sid, shex = data["seed_id"], f"{data['seed']:08X}"
            self._seed_cache = SeedCacheEntry(timestamp=now, seed_id=sid, seed_hex=shex)
            self._connected = True
            return sid, shex
        except Exception as e:
            self._log_fn(f"  API error: {e}")
            self._connected = False
            return self._seed_cache.seed_id or None, self._seed_cache.seed_hex

    def refresh_current_seed(self) -> None:
        """Force-refresh the cached seed (used by the dashboard refresh loop)."""
        try:
            req = Request(
                f"{API_BASE}/api/seed/current",
                headers={"User-Agent": USER_AGENT},
            )
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            self._seed_cache = SeedCacheEntry(
                timestamp=time.time(),
                seed_id=data["seed_id"],
                seed_hex=f"{data['seed']:08X}",
            )
            self._connected = True
        except Exception:
            self._connected = False

    def seed_remaining_minutes(self, seed_id: int) -> float:
        """Estimated minutes remaining before *seed_id* expires."""
        csid, _ = self.get_current_seed()
        if not csid:
            return 9999.0
        return 24.0 * 60.0 - (csid - seed_id) * 10.0

    def enough_time(
        self, seed_id: int, salts_left: int, salt_time_seconds: float
    ) -> tuple[bool, float, float]:
        """Check whether there is enough time for *salts_left* salts.

        Returns ``(is_enough, remaining_minutes, needed_minutes)``.
        """
        remaining_minutes = self.seed_remaining_minutes(seed_id)
        needed_minutes = (
            salts_left * (salt_time_seconds / 60.0) + MIN_REMAINING_FINISH_MINUTES
        )
        return remaining_minutes >= needed_minutes, remaining_minutes, needed_minutes

    # ── Proof endpoints ───────────────────────────────────────────
    def fetch_proof_status(self, job_id: str) -> dict[str, Any]:
        """Return proof/job status for a single *job_id*, cached per TTL."""
        now = time.time()
        cached = self._proof_cache.get(job_id)
        if cached and now - cached.get("_fetched", 0) < self._proof_cache_ttl:
            return cached
        try:
            req = Request(
                f"{API_BASE}/api/proofs/jobs/{job_id}",
                headers={"User-Agent": USER_AGENT},
            )
            data = json.loads(urlopen(req, timeout=10).read())
            job = data.get("job", {})
            result: dict[str, Any] = {
                "status": job.get("status", "unknown"),
                "score": job.get("tape", {}).get("metadata", {}).get("finalScore", 0),
                "prover": job.get("prover", {}).get("status", ""),
                "claim": job.get("claim", {}).get("status", ""),
                "replay_url": f"https://kalien.xyz/replay/{job_id}",
                "_fetched": now,
            }
            self._proof_cache[job_id] = result
            return result
        except Exception:
            return {
                "status": "unknown",
                "replay_url": f"https://kalien.xyz/replay/{job_id}",
                "_fetched": now,
            }

    def get_all_proofs(self, seeds: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch-fetch proof status for all submitted seeds, cached 60 s."""
        now = time.time()
        if (
            self._proofs_result_cache is not None
            and now - self._proofs_result_ts < self._proofs_result_ttl
        ):
            return self._proofs_result_cache

        proofs: dict[str, Any] = {}
        for s in seeds:
            jid = s.get("submitted_job_id", "")
            if jid:
                proofs[s["seed_hex"]] = self.fetch_proof_status(jid)

        self._proofs_result_cache = proofs
        self._proofs_result_ts = now
        return proofs
