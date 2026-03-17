"""Runner orchestration — the main beam-search pipeline loop."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from kalien.api_client import KalienAPI
from kalien.config import (
    DEFAULT_PUSH_THRESHOLD,
    MIN_REMAINING_HOURS,
    PUSH_SALTS,
    QUALIFY_SALTS,
    RunnerPaths,
    ensure_data_dir,
    find_engine,
    now_iso,
)
from kalien.db import Database
from kalien.engine import run_phase
from kalien.hardware import HardwareInfo, detect_hardware, load_or_benchmark
from kalien.queue import parse_queue_entry, pop_queue, push_queue_front
from kalien.settings import load_settings
from kalien.state import clear_state, load_state, record_result, save_state
from kalien.submission import SubmitError, submit_best_from_dir


# ── Runner Context ────────────────────────────────────────────────────
class RunnerContext:
    """Holds all shared resources and configuration for the runner."""

    def __init__(
        self,
        binary: Path,
        hw: HardwareInfo,
        threads: int,
        paths: RunnerPaths,
        salt_time_est_seconds: float,
        qualify_beam: int,
        push_beam: int,
        claimant: str,
    ) -> None:
        self.binary = binary
        self.hw = hw
        self.threads = threads
        self.paths = paths
        self.salt_time_est_seconds = salt_time_est_seconds
        self.qualify_beam = qualify_beam
        self.push_beam = push_beam
        self.claimant = claimant
        self.api = KalienAPI(log_fn=self.log)
        self.db = Database(paths.db)
        self._log_fh: Any = None

    def close(self) -> None:
        """Release open file handles."""
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    # ── Logging ───────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        """Write *msg* to both stdout and the runner log file."""
        if self._log_fh is None:
            self._log_fh = open(self.paths.log, "a", buffering=1)
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        self._log_fh.write(line + "\n")

    # ── Settings ──────────────────────────────────────────────────
    def get_push_threshold(self) -> int:
        """Read the push threshold from settings (may be changed by the dashboard)."""
        try:
            if self.paths.settings.exists():
                s = load_settings(self.paths.settings)
                return int(s.get("push_threshold", DEFAULT_PUSH_THRESHOLD))
        except Exception:
            pass
        return DEFAULT_PUSH_THRESHOLD

    # ── Pause Support ─────────────────────────────────────────────
    def check_pause(self) -> None:
        """Block while the pause file exists."""
        if self.paths.pause.exists():
            self.log("PAUSED — remove pause file to resume")
            self.paths.status.write_text(f"paused {now_iso()}\n")
            while self.paths.pause.exists():
                time.sleep(5)
            self.log("RESUMED")


# ── Phase Completion ──────────────────────────────────────────────────
def handle_phase_completion(state: dict[str, Any], ctx: RunnerContext) -> None:
    """Post-run bookkeeping for a completed (non-aborted) phase.

    Records results, updates the DB, submits the best tape, and queues
    a push run if the seed qualified.
    """
    record_result(ctx.paths.results, state)
    outdir = state["outdir"]
    seed = state["seed"]
    sid = state["seed_id"]

    if state["phase"] == "qualify":
        ctx.db.update_qualify(
            seed, state["best_score"], state["best_salt"], state["elapsed"]
        )
        submit_best_from_dir(
            outdir, sid, seed, ctx.claimant, ctx.db, log_fn=ctx.log
        )
        threshold = ctx.get_push_threshold()
        if state["best_score"] > threshold:
            ctx.log(
                f"*** {seed} qualified with {state['best_score']:,} — "
                f"queuing push w={ctx.push_beam}x{PUSH_SALTS} ***"
            )
            push_queue_front(
                ctx.paths.queue,
                f"{seed}:{sid}:{PUSH_SALTS}:0:{ctx.push_beam}",
            )
            ctx.db.update_push(seed, "queued", beam=ctx.push_beam, salts_total=PUSH_SALTS)
    else:
        total = state["salt_end"] - state.get("salt_start_orig", 0)
        ctx.db.update_push(
            seed,
            "completed",
            beam=state["beam"],
            score=state["best_score"],
            salt=state["best_salt"],
            salts_done=total,
            salts_total=total,
            elapsed=state["elapsed"],
        )
        submit_best_from_dir(
            outdir, sid, seed, ctx.claimant, ctx.db, log_fn=ctx.log
        )


# ── Resume Logic ──────────────────────────────────────────────────────
def try_resume(ctx: RunnerContext, push_time_est_seconds: float) -> None:
    """Resume an interrupted run if one exists and the seed has not expired."""
    state = load_state(ctx.paths.state)
    if not state or not state.get("phase") or not state.get("seed"):
        return

    salts_left = state["salt_end"] - state["salt_current"]
    ok, rem, _needed = ctx.api.enough_time(
        state["seed_id"], salts_left, push_time_est_seconds
    )
    if not ok:
        ctx.log(f"RESUME skipped — {state['seed']} expired ({rem:.0f} min left)")
        ctx.db.update_push(state["seed"], "expired")
        clear_state(ctx.paths.state)
        return

    ctx.log(
        f"RESUMING: {state['seed']} phase={state['phase']} "
        f"salt={state['salt_current']}/{state['salt_end']}"
    )
    start = time.time()
    state = run_phase(state, ctx)
    state["elapsed"] = int(time.time() - start)

    if not state.get("aborted"):
        handle_phase_completion(state, ctx)
    clear_state(ctx.paths.state)


# ── Main Loop Body ────────────────────────────────────────────────────
def process_one_seed(ctx: RunnerContext) -> bool:
    """Process one seed from the queue (or the current API seed).

    Returns ``True`` if a seed was processed, ``False`` if the queue was
    empty and no seed could be fetched (caller should sleep and retry).
    """
    line = pop_queue(ctx.paths.queue, ctx.qualify_beam)
    if line is None:
        csid, cseed = ctx.api.get_current_seed()
        if csid and cseed:
            ctx.log(f"Queue empty — fetching current seed {cseed}")
            line = f"{cseed}:{csid}"
        else:
            ctx.paths.status.write_text(f"idle {now_iso()}\n")
            return False

    entry = parse_queue_entry(line)
    if entry is None:
        ctx.log(f"SKIP malformed queue entry: {line!r}")
        return True
    ctx.db.record_seed(entry.seed, entry.seed_id)

    # Expiry check
    rem = ctx.api.seed_remaining_minutes(entry.seed_id)
    if rem < MIN_REMAINING_HOURS * 60:
        ctx.log(f"SKIP {entry.seed} — expired ({rem:.0f} min remaining)")
        ctx.db.update_push(entry.seed, "expired")
        return True

    # Determine phase
    if entry.beam and entry.beam > ctx.qualify_beam:
        phase, beam = "push", entry.beam
        salts = entry.salts or PUSH_SALTS
        s_start = entry.salt_start
    elif entry.salts is not None:
        phase, beam = "push", entry.beam or ctx.push_beam
        salts = entry.salts
        s_start = entry.salt_start
    else:
        phase, beam = "qualify", ctx.qualify_beam
        salts, s_start = QUALIFY_SALTS, 0

    outdir = ctx.paths.base / entry.seed.lower()
    state: dict[str, Any] = {
        "phase": phase,
        "seed": entry.seed,
        "seed_id": entry.seed_id,
        "beam": beam,
        "salt_current": s_start,
        "salt_start_orig": s_start,
        "salt_end": s_start + salts,
        "best_score": 0,
        "best_salt": "unknown",
        "outdir": str(outdir),
        "started": now_iso(),
    }
    save_state(ctx.paths.state, state)

    if phase == "push":
        ctx.db.update_push(entry.seed, "running", beam=beam, salts_total=salts)

    ctx.log(
        f"{phase.upper()} {entry.seed} "
        f"(id={entry.seed_id}, w={beam}, salts={s_start}..{s_start + salts - 1}, "
        f"{rem:.0f}min left)"
    )

    start = time.time()
    state = run_phase(state, ctx)
    state["elapsed"] = int(time.time() - start)

    if state.get("aborted"):
        ctx.log(
            f"ABORTED: {entry.seed} ({state['aborted']}) "
            f"best={state['best_score']:,} ({state['elapsed']}s)"
        )
        clear_state(ctx.paths.state)
        return True

    ctx.log(
        f"DONE: {entry.seed} best={state['best_score']:,} "
        f"salt={state['best_salt']} w={beam} ({state['elapsed']}s)"
    )

    handle_phase_completion(state, ctx)
    clear_state(ctx.paths.state)
    ctx.log("")
    return True


# ── Main ──────────────────────────────────────────────────────────────
def main() -> None:
    """Entry point for the runner CLI."""
    parser = argparse.ArgumentParser(
        description="Kalien Runner — unified beam search pipeline"
    )
    parser.add_argument(
        "--level", choices=["high", "low"], default="high", help="Performance level"
    )
    parser.add_argument(
        "--benchmark", action="store_true", help="Force re-benchmark"
    )
    parser.add_argument("--beam", type=int, help="Override beam width")
    parser.add_argument(
        "--dir", type=str, help="Data directory (default: ./tapes)"
    )
    parser.add_argument("--binary", type=str, help="Path to kalien binary")
    parser.add_argument(
        "--threads", type=int, help="CPU threads (auto-detected)"
    )
    args = parser.parse_args()

    # Find binary
    binary = Path(args.binary) if args.binary else find_engine()
    if not binary or not binary.exists():
        print("ERROR: Cannot find kalien binary. Use --binary to specify path.")
        sys.exit(1)

    # Setup paths
    from kalien.config import PROJECT_ROOT

    base = Path(args.dir) if args.dir else PROJECT_ROOT / "tapes"
    ensure_data_dir(base)
    paths = RunnerPaths.from_base(base)
    paths.queue.touch()

    # Detect hardware
    hw = detect_hardware()

    # Load settings (claimant, thresholds, etc.)
    settings = load_settings(paths.settings)
    claimant = settings["claimant"]

    # Temporary log function for the benchmark phase
    def _early_log(msg: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(paths.log, "a") as fh:
            fh.write(line + "\n")

    _early_log(f"Hardware: {hw.summary()}")
    if not claimant:
        _early_log(
            "WARNING: No claimant address configured. Tapes will NOT be submitted."
        )
        _early_log(
            "  Set your Stellar address in tapes/settings.json or the dashboard Setup tab."
        )

    # Benchmark / load config
    config = load_or_benchmark(
        paths.config, binary, hw, args.level, _early_log,
        force=args.benchmark, status_path=paths.status,
    )
    if not config:
        _early_log("Benchmark failed!")
        sys.exit(1)

    qualify_beam = args.beam or config["qualify_beam"]
    push_beam = args.beam or config["push_beam"]
    threads = args.threads or config.get("threads", hw.cpu_cores)
    push_time_est_seconds: float = config.get("push_salt_time_est", 360)

    # Build context
    ctx = RunnerContext(
        binary=binary,
        hw=hw,
        threads=threads,
        paths=paths,
        salt_time_est_seconds=push_time_est_seconds,
        qualify_beam=qualify_beam,
        push_beam=push_beam,
        claimant=claimant,
    )
    ctx.db.init_schema()

    ctx.log("=" * 60)
    ctx.log(f"Kalien Runner started ({hw.mode.upper()}, level={args.level})")
    ctx.log(
        f"  Qualify: w={qualify_beam}, Push: w={push_beam}, "
        f"Threshold: {ctx.get_push_threshold():,}"
    )
    ctx.log(f"  Threads: {threads}, Binary: {binary}")
    ctx.log("=" * 60)

    # Resume interrupted run (if any)
    try_resume(ctx, push_time_est_seconds)

    # Main loop
    while True:
        ctx.check_pause()
        if not process_one_seed(ctx):
            time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"[{now_iso()}] Interrupted (Ctrl+C)", flush=True)
    except Exception as e:
        print(f"[{now_iso()}] FATAL: {e}", flush=True)
        raise
