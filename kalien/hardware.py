"""Hardware detection and engine benchmarking."""
from __future__ import annotations

import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from kalien.config import (
    BENCHMARK_SEED,
    BRANCHES,
    FRAMES,
    HORIZON,
    now_iso,
)


@dataclass
class HardwareInfo:
    """Detected hardware capabilities (GPU or CPU)."""

    mode: str = "cpu"  # "cpu" or "gpu"
    gpu_name: Optional[str] = None
    gpu_vram_mb: int = 0
    cpu_cores: int = field(default_factory=lambda: os.cpu_count() or 4)
    cpu_model: str = field(default_factory=lambda: platform.processor() or "unknown")

    def summary(self) -> str:
        """One-line human-readable description."""
        if self.mode == "gpu":
            return f"GPU — {self.gpu_name} ({self.gpu_vram_mb}MB VRAM)"
        return f"CPU — {self.cpu_model} ({self.cpu_cores} cores)"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (for JSON storage)."""
        return {
            "mode": self.mode,
            "gpu_name": self.gpu_name,
            "gpu_vram_mb": self.gpu_vram_mb,
            "cpu_cores": self.cpu_cores,
            "cpu_model": self.cpu_model,
        }


def detect_hardware() -> HardwareInfo:
    """Probe for an NVIDIA GPU; fall back to CPU info."""
    hw = HardwareInfo()
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split(",")
            hw.mode = "gpu"
            hw.gpu_name = parts[0].strip()
            hw.gpu_vram_mb = int(parts[1].strip()) if len(parts) > 1 else 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return hw


# ── Benchmarking ──────────────────────────────────────────────────────
def run_benchmark(
    binary: Path,
    hw: HardwareInfo,
    level: str,
    log_fn: Callable[[str], None],
    status_path: Optional[Path] = None,
    log_fh: Any = None,
) -> Optional[dict[str, Any]]:
    """Run a short benchmark to calibrate beam widths.

    Returns a config dict on success, or ``None`` on failure.
    If *status_path* is given, writes frame progress for the dashboard.
    """
    log_fn(f"Benchmarking... (mode={hw.mode}, level={level})")

    test_beam = 4096 if hw.mode == "gpu" else 2048
    threads = hw.cpu_cores
    if level == "low":
        threads = max(1, threads // 2)

    with tempfile.TemporaryDirectory(prefix="kalien_bench_") as tmpdir:
        cmd = [
            str(binary),
            "--seed", f"0x{BENCHMARK_SEED}",
            "--out", os.path.join(tmpdir, "bench"),
            "--beam", str(test_beam),
            "--branches", str(BRANCHES),
            "--horizon", str(HORIZON),
            "--frames", str(FRAMES),
            "--iterations", "1",
            "--salt", "0",
        ]
        if hw.mode == "cpu":
            cmd += ["--threads", str(threads)]

        log_fn(
            f"  Running w={test_beam}, "
            f"{'threads=' + str(threads) if hw.mode == 'cpu' else 'GPU'}..."
        )
        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            current_frame = 0
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace")
                sys.stdout.write(line)
                sys.stdout.flush()
                # Write to log file too
                if log_fh:
                    log_fh.write(line)
                m = re.search(r"frame=(\d+)", line)
                if m:
                    current_frame = int(m.group(1))
                    # Write benchmark progress to status file
                    if status_path:
                        status_path.write_text(
                            f"benchmarking w={test_beam} "
                            f"frame={current_frame}/{FRAMES} "
                            f"{math.floor(current_frame/FRAMES*100)}%\n"
                        )
            exit_code = proc.wait()
        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[union-attr]
            log_fn("  Benchmark timed out at 10 minutes")
            return None
        if exit_code != 0:
            log_fn(f"  Benchmark failed: engine exited with code {exit_code}")
            return None
        elapsed = time.time() - start

    log_fn(f"  Benchmark: w={test_beam} took {elapsed:.1f}s")

    if elapsed < 1:
        elapsed = 1.0  # safety floor

    # Extrapolate: time scales ~linearly with beam width
    rate = elapsed / test_beam  # seconds per beam unit

    # Qualify: must finish in <9 min (540 s) for 1 salt
    max_qualify = int(test_beam * (540 / elapsed) * 0.85)
    # Push: must finish in <4 hrs (14400 s) for 30 salts -> 480 s per salt
    max_push = int(test_beam * (480 / elapsed) * 0.85)

    if level == "low":
        max_qualify //= 2
        max_push //= 2

    # GPU VRAM cap: ~63 KB per beam unit
    if hw.mode == "gpu" and hw.gpu_vram_mb:
        vram_cap = int((hw.gpu_vram_mb - 500) * 1024 / 63)
        max_qualify = min(max_qualify, vram_cap)
        max_push = min(max_push, vram_cap)

    # Round to nearest 1024
    max_qualify = max(1024, (max_qualify // 1024) * 1024)
    max_push = max(1024, (max_push // 1024) * 1024)

    config: dict[str, Any] = {
        "version": 1,
        "timestamp": now_iso(),
        "hardware": hw.to_dict(),
        "level": level,
        "benchmark": {
            "test_beam": test_beam,
            "test_time": round(elapsed, 2),
            "rate": round(rate, 6),
        },
        "qualify_beam": max_qualify,
        "push_beam": max_push,
        "threads": threads,
        "qualify_time_est": round(max_qualify * rate),
        "push_salt_time_est": round(max_push * rate),
    }
    log_fn(
        f"  Calibrated: qualify w={max_qualify} (~{config['qualify_time_est']}s), "
        f"push w={max_push} (~{config['push_salt_time_est']}s/salt)"
    )
    return config


def load_or_benchmark(
    config_path: Path,
    binary: Path,
    hw: HardwareInfo,
    level: str,
    log_fn: Callable[[str], None],
    force: bool = False,
    status_path: Optional[Path] = None,
    log_fh: Any = None,
) -> Optional[dict[str, Any]]:
    """Load a cached benchmark config, or run a new benchmark."""
    if not force and config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            cached_hw = config.get("hardware", {})
            hw_match = (
                cached_hw.get("mode") == hw.mode
                and cached_hw.get("cpu_cores") == hw.cpu_cores
                and cached_hw.get("cpu_model") == hw.cpu_model
                and cached_hw.get("gpu_name") == hw.gpu_name
                and cached_hw.get("gpu_vram_mb") == hw.gpu_vram_mb
            )
            if config.get("level") == level and hw_match:
                log_fn(
                    f"Loaded config: qualify w={config['qualify_beam']}, "
                    f"push w={config['push_beam']}"
                )
                return config
            elif not hw_match:
                log_fn("Hardware changed since last benchmark — re-benchmarking")
        except Exception:
            pass

    config = run_benchmark(binary, hw, level, log_fn, status_path=status_path, log_fh=log_fh)
    if config:
        config_path.write_text(json.dumps(config, indent=2))
    return config
