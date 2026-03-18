"""Running the kalien beam-search binary."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from kalien.config import (
    BRANCHES,
    EXPIRY_RECHECK_SALTS,
    FRAMES,
    HORIZON,
    now_iso,
)
from kalien.state import save_state

if TYPE_CHECKING:
    from kalien.hardware import HardwareInfo
    from kalien.runner import RunnerContext


def run_one_salt(
    binary: Path,
    seed: str,
    beam: int,
    salt: int,
    outdir: Path,
    hw: HardwareInfo,
    threads: int,
    status_path: Optional[Path] = None,
    phase: str = "",
    salt_idx: int = 0,
    salt_total: int = 1,
) -> tuple[int, Optional[str]]:
    """Run a single salt iteration.

    Returns ``(score, salt_hex)``.  A score of ``-1`` signals an engine
    failure (distinct from a legitimate score of 0).

    If *status_path* is provided, writes frame-level progress to it so
    the dashboard can show live updates.
    """
    log_file = outdir / f"log_w{beam}_s{salt}.txt"
    cmd = [
        str(binary),
        "--seed", f"0x{seed}",
        "--out", str(outdir / "run"),
        "--beam", str(beam),
        "--branches", str(BRANCHES),
        "--horizon", str(HORIZON),
        "--frames", str(FRAMES),
        "--iterations", "1",
        "--salt", str(salt),
    ]
    if hw.mode == "cpu":
        cmd += ["--threads", str(threads)]
    try:
        with open(log_file, "w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            score, salt_hex = 0, f"0x{salt:08x}"
            current_frame = 0
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace")
                lf.write(line)
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass  # skip unprintable lines on Windows console
                m = re.search(r"best=(\d+)", line)
                if m:
                    score = int(m.group(1))
                m = re.search(r"salt=(0x[0-9a-fA-F]+)", line)
                if m:
                    salt_hex = m.group(1)
                m = re.search(r"frame=(\d+)", line)
                if m and status_path:
                    current_frame = int(m.group(1))
                    status_path.write_text(
                        f"running {seed} {now_iso()} {phase} w={beam} "
                        f"salt={salt_idx}/{salt_total} "
                        f"frame={current_frame}/{FRAMES} "
                        f"score={score}\n"
                    )
            exit_code = proc.wait()
        if exit_code != 0:
            print(
                f"  WARNING: engine exited with code {exit_code} for salt {salt}",
                flush=True,
            )
            return -1, None
        return score, salt_hex
    except Exception as e:
        print(f"  ERROR running salt {salt}: {e}", flush=True)
        return -1, None


def run_phase(state: dict[str, Any], ctx: RunnerContext) -> dict[str, Any]:
    """Run salts one at a time, updating *state* after each.

    Returns the final state dict.
    """
    seed, sid = state["seed"], state["seed_id"]
    beam, phase = state["beam"], state["phase"]
    outdir = Path(state["outdir"])
    outdir.mkdir(parents=True, exist_ok=True)

    while state["salt_current"] < state["salt_end"]:
        ctx.check_pause()

        # Expiry check every N salts
        if (
            state["salt_current"] > 0
            and state["salt_current"] % EXPIRY_RECHECK_SALTS == 0
        ):
            salts_left = state["salt_end"] - state["salt_current"]
            ok, rem, needed = ctx.api.enough_time(
                sid, salts_left, ctx.salt_time_est_seconds
            )
            if not ok:
                ctx.log(
                    f"  EXPIRED: {rem:.0f} min left, need {needed:.0f} — aborting"
                )
                state["aborted"] = "expired"
                save_state(ctx.paths.state, state)
                ctx.db.update_push(
                    seed,
                    "expired",
                    beam=beam,
                    score=state["best_score"],
                    salt=state["best_salt"],
                    salts_done=state["salt_current"],
                    salts_total=state["salt_end"] - state.get("salt_start_orig", 0),
                )
                return state

        salt = state["salt_current"]
        total = state["salt_end"]
        ctx.log(f"  salt {salt}/{total-1} (w={beam}, seed={seed})")
        ctx.paths.status.write_text(
            f"running {seed} {now_iso()} {phase} w={beam} salt={salt}/{total-1}\n"
        )

        salts_done_so_far = salt - state.get("salt_start_orig", 0)
        salts_total = state["salt_end"] - state.get("salt_start_orig", 0)
        score, salt_hex = run_one_salt(
            ctx.binary, seed, beam, salt, outdir, ctx.hw, ctx.threads,
            status_path=ctx.paths.status, phase=phase,
            salt_idx=salts_done_so_far, salt_total=salts_total,
        )

        if score < 0:
            ctx.log(f"  Engine failed on salt {salt} — skipping")
            state["salt_current"] = salt + 1
            save_state(ctx.paths.state, state)
            continue

        if score > state["best_score"]:
            state["best_score"] = score
            state["best_salt"] = salt_hex or f"0x{salt:08x}"
            ctx.log(f"  NEW BEST: {score} (salt={state['best_salt']})")

            # Submit immediately on each new best during push
            if phase == "push":
                from kalien.submission import SubmitError, submit_best_from_dir
                try:
                    submit_best_from_dir(
                        str(outdir), sid, seed, ctx.claimant, ctx.db,
                        log_fn=ctx.log,
                    )
                except Exception as e:
                    ctx.log(f"  Submit error: {e}")

        state["salt_current"] = salt + 1
        save_state(ctx.paths.state, state)

        if phase == "push":
            salts_done = state["salt_current"] - state.get("salt_start_orig", 0)
            salts_total = state["salt_end"] - state.get("salt_start_orig", 0)

            # Time-box check: stop if we've exceeded the time limit
            # Default to matching tier if not set (handles old state files)
            time_limit = state.get("time_limit", 0)
            if time_limit == 0 and phase == "push":
                from kalien.config import PUSH_TIERS
                for tier in PUSH_TIERS:
                    if beam <= tier["beam"]:
                        time_limit = tier["hours"] * 3600
                        break
                if not time_limit:
                    time_limit = PUSH_TIERS[-1]["hours"] * 3600
                state["time_limit"] = time_limit
            if time_limit > 0:
                elapsed = time.time() - ctx._phase_start_time
                if elapsed >= time_limit:
                    hours = time_limit / 3600
                    ctx.log(
                        f"  TIME LIMIT: {hours:.0f}h reached after {salts_done} salts "
                        f"— best={state['best_score']:,}"
                    )
                    # Adjust salt_end so handle_phase_completion sees correct totals
                    state["salt_end"] = state["salt_current"]
                    save_state(ctx.paths.state, state)
                    return state

            ctx.db.update_push(
                seed,
                "running",
                beam=beam,
                score=state["best_score"],
                salt=state["best_salt"],
                salts_done=salts_done,
                salts_total=salts_total,
            )
    return state
