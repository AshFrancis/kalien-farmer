"""Tape submission to the kalien.xyz proof pipeline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kalien.config import API_BASE, USER_AGENT
from kalien.db import Database
from kalien.settings import CLAIMANT_PLACEHOLDERS


class SubmitError(Exception):
    """Raised when tape submission fails."""


def submit_tape(
    tape_path: str,
    seed_id: int,
    claimant: str,
    *,
    api_base: str = API_BASE,
    log_fn: Callable[[str], None] = lambda _m: None,
) -> str:
    """Submit a tape file to kalien.xyz.

    Returns the job ID on success.  Raises :class:`SubmitError` with a
    human-readable message on failure.
    """
    if not claimant or claimant.upper() in CLAIMANT_PLACEHOLDERS:
        raise SubmitError(
            "No valid claimant address configured. "
            "Set it in settings.json or the dashboard Setup tab."
        )
    if len(claimant) != 56 or claimant[0] not in "GC":
        raise SubmitError(
            f"Invalid claimant address format: {claimant[:10]}... "
            "(must be 56 chars starting with G or C)"
        )

    with open(tape_path, "rb") as f:
        tape_data = f.read()

    url = f"{api_base}/api/proofs/jobs?claimant={claimant}&seed_id={seed_id}"
    req = Request(
        url,
        data=tape_data,
        headers={
            "Content-Type": "application/octet-stream",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("success"):
                job = data.get("job", {})
                job_id = job.get("jobId", "unknown")
                score = job.get("tape", {}).get("metadata", {}).get("finalScore", "?")
                log_fn(f"  SUBMITTED! Job={job_id} Score={score}")
                return job_id
            else:
                error_msg = data.get("error", "unknown API error")
                log_fn(f"  Submit error: {error_msg}")
                raise SubmitError(f"API rejected submission: {error_msg}")
    except HTTPError as e:
        body = e.read().decode()[:200]
        log_fn(f"  HTTP {e.code}: {body}")
        raise SubmitError(f"HTTP {e.code}: {body}") from e
    except SubmitError:
        raise
    except Exception as e:
        log_fn(f"  Submit error: {e}")
        raise SubmitError(str(e)) from e


def submit_best_from_dir(
    outdir: str,
    seed_id: int,
    seed_hex: str,
    claimant: str,
    db: Database,
    *,
    min_score: int = 0,
    api_base: str = API_BASE,
    log_fn: Callable[[str], None] = lambda _m: None,
) -> None:
    """Find the best tape in *outdir* and submit it if its score exceeds *min_score*."""
    tapes = list(Path(outdir).glob("*.tape"))
    if not tapes:
        return

    best_tape: Optional[Path] = None
    best_score = 0
    for t in tapes:
        m = re.search(r"_(\d+)\.tape$", t.name)
        if m:
            s = int(m.group(1))
            if s > best_score:
                best_score, best_tape = s, t
    if not best_tape or best_score <= min_score:
        return

    # Check if we already submitted this score or better
    with db.connect() as conn:
        row = conn.execute(
            "SELECT submitted_score FROM seeds WHERE seed_hex=?", (seed_hex,)
        ).fetchone()
    prev = row[0] if row else 0
    if best_score <= prev:
        log_fn(f"  Already submitted {seed_hex} with {prev:,} >= {best_score:,}")
        return

    log_fn(f"  Submitting {seed_hex}: {best_score:,} ({best_tape.name})")
    try:
        job_id = submit_tape(
            str(best_tape), seed_id, claimant, api_base=api_base, log_fn=log_fn
        )
        db.update_submitted(seed_hex, best_score, job_id)
    except SubmitError as e:
        log_fn(f"  Submission failed for {seed_hex}: {e}")
