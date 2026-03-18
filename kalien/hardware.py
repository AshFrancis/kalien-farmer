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
        if self.mode == "gpu":
            return f"GPU — {self.gpu_name} ({self.gpu_vram_mb}MB VRAM)"
        return f"CPU — {self.cpu_model} ({self.cpu_cores} cores)"

    def to_dict(self) -> dict[str, Any]:
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


def _engine_supports_gpu(binary: Path) -> bool:
    """Check if the engine binary was compiled with GPU support."""
    try:
        r = subprocess.run(
            [str(binary), "--help"],
            capture_output=True, text=True, timeout=5,
        )
        # GPU builds show --device and --gpu options in help
        return "--device" in r.stderr or "--device" in r.stdout
    except Exception:
        return False


# ── Benchmarking ──────────────────────────────────────────────────────
def _run_single_benchmark(
    binary: Path,
    mode: str,
    test_beam: int,
    threads: int,
    log_fn: Callable[[str], None],
    status_path: Optional[Path] = None,
    log_fh: Any = None,
) -> Optional[float]:
    """Run a single benchmark and return elapsed seconds, or None on failure."""
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
        if mode == "cpu":
            cmd += ["--cpu", "--threads", str(threads)]

        label = f"{'CPU threads=' + str(threads) if mode == 'cpu' else 'GPU'}"
        log_fn(f"  Running w={test_beam}, {label}...")
        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace")
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                if log_fh:
                    try:
                        log_fh.write(line)
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                m = re.search(r"frame=(\d+)", line)
                if m and status_path:
                    frame = int(m.group(1))
                    status_path.write_text(
                        f"benchmarking {mode} w={test_beam} "
                        f"frame={frame}/{FRAMES} "
                        f"{math.floor(frame / FRAMES * 100)}%\n"
                    )
            exit_code = proc.wait()
        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[union-attr]
            log_fn(f"  Benchmark ({mode}) timed out")
            return None
        if exit_code != 0:
            log_fn(f"  Benchmark ({mode}) failed: exit code {exit_code}")
            return None
        return time.time() - start


def _calibrate(elapsed: float, test_beam: int, level: str,
               hw: HardwareInfo, mode: str) -> dict[str, Any]:
    """Compute beam widths from a benchmark timing."""
    if elapsed < 1:
        elapsed = 1.0

    rate = elapsed / test_beam  # seconds per beam unit

    # Qualify: must finish in <9 min (540 s)
    max_qualify = int(test_beam * (540 / elapsed) * 0.85)
    max_push = max_qualify * 3

    if level == "low":
        max_qualify //= 2
        max_push //= 2

    # GPU VRAM cap
    if mode == "gpu" and hw.gpu_vram_mb:
        vram_cap = int((hw.gpu_vram_mb - 500) * 1024 / 63)
        max_qualify = min(max_qualify, vram_cap)
        max_push = min(max_push, vram_cap)

    max_qualify = max(1024, (max_qualify // 1024) * 1024)
    max_push = max(1024, (max_push // 1024) * 1024)

    return {
        "test_beam": test_beam,
        "test_time": round(elapsed, 2),
        "rate": round(rate, 6),
        "qualify_beam": max_qualify,
        "push_beam": max_push,
        "qualify_time_est": round(max_qualify * rate),
        "push_salt_time_est": round(max_push * rate),
    }


def run_benchmark(
    binary: Path,
    hw: HardwareInfo,
    level: str,
    log_fn: Callable[[str], None],
    status_path: Optional[Path] = None,
    log_fh: Any = None,
) -> Optional[dict[str, Any]]:
    """Run benchmarks and return config dict.

    If the engine supports GPU and an NVIDIA GPU is detected, benchmarks
    both CPU and GPU sequentially and picks the faster one as default.
    """
    has_gpu = hw.mode == "gpu" and _engine_supports_gpu(binary)
    threads = hw.cpu_cores
    if level == "low":
        threads = max(1, threads // 2)

    # Always benchmark CPU
    cpu_test_beam = 2048
    log_fn(f"Benchmarking CPU (mode=cpu, level={level})")
    cpu_elapsed = _run_single_benchmark(
        binary, "cpu", cpu_test_beam, threads, log_fn,
        status_path=status_path, log_fh=log_fh,
    )
    if cpu_elapsed is None:
        return None
    log_fn(f"  CPU benchmark: w={cpu_test_beam} took {cpu_elapsed:.1f}s")
    cpu_cal = _calibrate(cpu_elapsed, cpu_test_beam, level, hw, "cpu")

    # Benchmark GPU if available
    gpu_cal = None
    if has_gpu:
        gpu_test_beam = 4096
        log_fn(f"Benchmarking GPU (mode=gpu, level={level})")
        gpu_elapsed = _run_single_benchmark(
            binary, "gpu", gpu_test_beam, threads, log_fn,
            status_path=status_path, log_fh=log_fh,
        )
        if gpu_elapsed is not None:
            log_fn(f"  GPU benchmark: w={gpu_test_beam} took {gpu_elapsed:.1f}s")
            gpu_cal = _calibrate(gpu_elapsed, gpu_test_beam, level, hw, "gpu")

    # Pick the faster mode as default
    best_mode = "cpu"
    best_cal = cpu_cal
    if gpu_cal and gpu_cal["qualify_beam"] > cpu_cal["qualify_beam"]:
        best_mode = "gpu"
        best_cal = gpu_cal

    log_fn(
        f"  Calibrated: {best_mode.upper()} qualify w={best_cal['qualify_beam']} "
        f"(~{best_cal['qualify_time_est']}s)"
    )
    if gpu_cal and cpu_cal:
        log_fn(
            f"  CPU: w={cpu_cal['qualify_beam']}, GPU: w={gpu_cal['qualify_beam']} "
            f"-> using {best_mode.upper()}"
        )

    config: dict[str, Any] = {
        "version": 2,
        "timestamp": now_iso(),
        "hardware": hw.to_dict(),
        "level": level,
        "selected_mode": best_mode,
        "cpu": cpu_cal,
        "benchmark": best_cal,  # backward compat
        "qualify_beam": best_cal["qualify_beam"],
        "push_beam": best_cal["push_beam"],
        "threads": threads,
        "qualify_time_est": best_cal["qualify_time_est"],
        "push_salt_time_est": best_cal["push_salt_time_est"],
    }
    if gpu_cal:
        config["gpu"] = gpu_cal

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
                cached_hw.get("cpu_cores") == hw.cpu_cores
                and cached_hw.get("cpu_model") == hw.cpu_model
                and cached_hw.get("gpu_name") == hw.gpu_name
                and cached_hw.get("gpu_vram_mb") == hw.gpu_vram_mb
            )
            if config.get("level") == level and hw_match:
                log_fn(
                    f"Loaded config: {config.get('selected_mode', 'cpu').upper()} "
                    f"qualify w={config['qualify_beam']}"
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
