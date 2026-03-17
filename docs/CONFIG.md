# Configuration Reference

## settings.json

Located at `tapes/settings.json`. Created on first run or by `setup.sh`. The runner and dashboard both read this file. The dashboard can write to it via the Settings tab or the `/api/settings` endpoint.

| Key | Type | Default | Description |
|---|---|---|---|
| `claimant` | string | (built-in default) | Stellar address (G... or C...) for receiving farming rewards. Required for tape submission. |
| `push_threshold` | int | `1190000` | Minimum qualify score to trigger a push run. Seeds scoring below this are discarded after qualification. Higher values mean fewer push runs but only on better seeds. |

Example:

```json
{
  "claimant": "GABCDEFGHIJKLMNOPQRSTUVWXYZ234567890ABCDEFGHIJKLMN",
  "push_threshold": 1190000
}
```

### How settings interact

- The runner re-reads `settings.json` between seeds, so changes take effect without restarting.
- `push_threshold` only affects the qualify-to-push decision. Seeds added manually to the queue with explicit salts and beam width bypass this threshold.
- If `claimant` is not set or is the placeholder value, tapes are still generated but submission will fail with an API error.

---

## CLI Arguments: kalien-farmer.py

```
python3 kalien-farmer.py [OPTIONS]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--port` | int | `8420` | HTTP port for the web dashboard |
| `--host` | string | `127.0.0.1` | Bind address. Use `0.0.0.0` to expose to the network (see [SECURITY.md](SECURITY.md)) |
| `--no-browser` | flag | off | Do not auto-open the browser on startup |

---

## CLI Arguments: runner.py

```
python3 runner.py [OPTIONS]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--level` | `high` or `low` | `high` | Performance level. `low` uses 50% of CPU threads and halves beam widths. Useful for running alongside other work. |
| `--benchmark` | flag | off | Force re-benchmark even if cached results exist |
| `--beam` | int | (auto) | Override beam width for both qualify and push phases. Bypasses calibration. |
| `--dir` | string | `./tapes` | Data directory for database, state, tapes, and logs |
| `--binary` | string | (auto-detect) | Path to the engine binary. Auto-detected from `engine/kalien`, `./kalien`, or `~/kalien-farmer/engine/kalien` |
| `--threads` | int | (auto) | CPU thread count for the engine. Defaults to all available cores. |

### Binary search order

When `--binary` is not specified, the runner searches these paths in order:

1. `{script_dir}/engine/kalien` (or `kalien.exe` on Windows)
2. `{script_dir}/kalien`
3. `~/kalien-farmer/engine/kalien`

---

## benchmark.json

Located at `tapes/benchmark.json`. Generated automatically by the runner's benchmarking phase. You generally do not need to edit this file.

```json
{
  "version": 1,
  "timestamp": "2026-03-17T14:00:00",
  "hardware": {
    "mode": "gpu",
    "gpu_name": "NVIDIA GeForce RTX 3080 Ti",
    "gpu_vram_mb": 12288,
    "cpu_cores": 16,
    "cpu_model": "AMD Ryzen 9 5950X"
  },
  "level": "high",
  "benchmark": {
    "test_beam": 4096,
    "test_time": 45.23,
    "rate": 0.011039
  },
  "qualify_beam": 40960,
  "push_beam": 36864,
  "threads": 16,
  "qualify_time_est": 452,
  "push_salt_time_est": 407
}
```

| Field | Description |
|---|---|
| `version` | Schema version (always 1) |
| `timestamp` | When the benchmark was run |
| `hardware` | Detected hardware at benchmark time |
| `hardware.mode` | `"cpu"` or `"gpu"` |
| `level` | Performance level used (`"high"` or `"low"`) |
| `benchmark.test_beam` | Beam width used for the test (4096 GPU, 2048 CPU) |
| `benchmark.test_time` | Wall-clock seconds for the test run |
| `benchmark.rate` | Seconds per beam unit (test_time / test_beam) |
| `qualify_beam` | Calibrated beam width for qualify phase |
| `push_beam` | Calibrated beam width for push phase |
| `threads` | CPU threads to use |
| `qualify_time_est` | Estimated seconds per qualify salt |
| `push_salt_time_est` | Estimated seconds per push salt |

The benchmark is invalidated and re-run automatically when:
- Hardware mode changes (GPU vs CPU)
- CPU core count or model changes
- GPU name or VRAM changes
- `--level` changes

**Not tracked** (use `--benchmark` to force re-run after these):
- Engine binary version changes (recompiled with optimizations)
- Compiler or build flag changes
- OS or driver updates
- Thermal/power state differences

---

## Engine Parameters (fixed)

These are hardcoded in `runner.py` and not user-configurable:

| Parameter | Value | Description |
|---|---|---|
| `BRANCHES` | 8 | Control variations per beam candidate |
| `HORIZON` | 20 | Lookahead depth in frames |
| `FRAMES` | 36000 | Total game frames to simulate |
| `QUALIFY_SALTS` | 1 | Salts per qualify run |
| `PUSH_SALTS` | 30 | Salts per push run |
| `MIN_REMAINING_HOURS` | 4 | Minimum hours left on seed to start processing |
| `MIN_REMAINING_FINISH_MINUTES` | 30 | Buffer time for submission after push completes |
| `EXPIRY_RECHECK_SALTS` | 5 | Check seed expiry every N salts during push |
| `BENCHMARK_SEED` | `DEADBEEF` | Fixed seed for benchmark reproducibility |

---

## Environment Variables

There are currently no environment variables used by the project. All configuration is via CLI arguments and `settings.json`.

---

## Overriding Defaults

For most users, the only setting to change is `claimant` in `settings.json`. The auto-benchmark handles beam width calibration, and the default push threshold works well.

To tune aggressively:
- **Lower `push_threshold`** to push more seeds (more compute, catches more opportunities)
- **Raise `push_threshold`** to push fewer seeds (less compute, only the best)
- **Use `--beam`** to override calibrated beam width (higher = better scores, slower)
- **Use `--level low`** to reduce resource usage to ~50%
