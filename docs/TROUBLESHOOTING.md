# Troubleshooting

## macOS: "cannot be opened because it is from an unidentified developer" / malware warning

**Cause:** macOS Gatekeeper blocks unsigned downloaded binaries.

**Fix:**

```bash
xattr -cr /path/to/kalien-farmer
chmod +x /path/to/kalien-farmer
```

Replace `/path/to/kalien-farmer` with the actual path (e.g. `~/Downloads/kalien-farmer`).

If you extracted from a DMG, you may need to copy it somewhere writable first (e.g. your home directory or `/usr/local/bin`).

---

## "Engine binary not found"

**Message:** `ERROR: Cannot find kalien binary. Use --binary to specify path.`

**Cause:** The runner could not find the compiled engine binary in any of its search paths.

**Fix:**

1. Build the engine:
   ```bash
   cd engine
   make CPU=1    # or just 'make' for GPU
   ```

2. Verify the binary exists:
   ```bash
   ls engine/kalien    # or engine/kalien.exe on Windows
   ```

3. If the binary is in a non-standard location, use `--binary`:
   ```bash
   python3 runner.py --binary /path/to/kalien
   ```

---

## "Benchmark failed"

**Message:** `Benchmark failed!` or `Benchmark failed: engine exited with code N`

**Causes and fixes:**

- **Engine binary is not executable:**
  ```bash
  chmod +x engine/kalien
  ```

- **Missing shared libraries (Linux GPU build):**
  ```bash
  # Check for missing libs
  ldd engine/kalien

  # Common fix: add CUDA to library path
  export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
  ```

- **Benchmark timed out (>10 minutes):** Your hardware may be too slow for the default test beam width. Try a smaller override:
  ```bash
  python3 runner.py --beam 1024
  ```

- **GPU out of memory:** The test beam width (4096) may exceed your GPU's VRAM. Use `--beam` with a smaller value, or build CPU-only.

---

## "API error"

**Message:** `API error: <URLError>` or similar

**Causes:**

- **Network issue:** Check your internet connection. The runner needs to reach `https://kalien.xyz`.
  ```bash
  curl https://kalien.xyz/api/seed/current
  ```

- **Firewall blocking HTTPS:** Ensure port 443 outbound is open.

- **kalien.xyz is down:** The API may be temporarily unavailable. The runner will retry automatically every 15 seconds.

- **DNS resolution failure:** Try `curl https://kalien.xyz` to diagnose.

The runner continues operating with cached seed data for up to 60 seconds when the API is unreachable.

---

## "Seed expired"

**Message:** `SKIP <seed> -- expired (N min remaining)` or `EXPIRED: N min left`

**This is normal behavior.** Seeds are valid for 24 hours from creation. The runner skips seeds with less than 4 hours remaining (not enough time for a full push run).

If you see many expirations, your machine may be too slow to keep up. Consider:
- Using `--level low` to reduce beam width and speed up runs
- Raising `push_threshold` to skip more seeds and only push the best ones

---

## "No seeds being processed"

**Check these in order:**

1. **Is the runner running?**
   - Dashboard: check the status indicator in the header
   - Terminal: `ps aux | grep runner.py`

2. **Is the runner paused?**
   ```bash
   ls tapes/pause    # if this file exists, the runner is paused
   rm tapes/pause    # to resume
   ```

3. **Is the API reachable?**
   ```bash
   curl https://kalien.xyz/api/seed/current
   ```

4. **Is the queue empty and the API down?**
   When both the queue is empty and the API is unreachable, the runner sleeps for 15 seconds and retries.

5. **Check the log:**
   ```bash
   tail -20 tapes/runner.log
   ```

---

## "Score is 0"

**Cause:** The engine ran but produced no meaningful output, or the engine crashed silently.

**Fix:**

1. Check the engine log for the specific salt:
   ```bash
   cat tapes/<seed_hex>/log_w*_s*.txt
   ```

2. Look for error messages or empty output.

3. Try running the engine manually:
   ```bash
   engine/kalien --seed 0xDEADBEEF --out /tmp/test --beam 1024 --branches 8 --horizon 20 --frames 1000 --iterations 1 --salt 0
   ```

4. If the engine segfaults, rebuild:
   ```bash
   cd engine && make clean && make CPU=1
   ```

---

## "Submission failed"

**Possible causes:**

- **Invalid claimant address:** Check `tapes/settings.json`. The `claimant` field must be a valid Stellar address (starts with G or C, 56 characters).

- **Seed expired on the API side:** Even if the runner thought it had time, the seed may have expired between the run and submission. Check the seed's age.

- **API rate limiting or server error:** The runner logs the HTTP status code and response body. Check `tapes/runner.log`.

- **Tape already submitted:** If a higher score was already submitted for this seed (by you or another machine), the runner skips resubmission. Check the `submitted_score` column in the SEEDS tab.

- **Network error during upload:** The runner does not retry failed submissions. The tape file is preserved, so you can resubmit manually if needed.

---

## "Dashboard won't start"

**Message:** `OSError: [Errno 48] Address already in use` (macOS/Linux) or similar

**Cause:** Port 8420 is already in use by another process.

**Fix:**

1. Use a different port:
   ```bash
   python3 kalien-farmer.py --port 9000
   ```

2. Find and stop the process using the port:
   ```bash
   # macOS / Linux
   lsof -i :8420
   kill <PID>

   # Windows
   netstat -ano | findstr :8420
   taskkill /F /PID <PID>
   ```

3. Check if another instance of kalien-farmer is already running.

---

## "Runner won't stop"

If the STOP button or Ctrl+C does not stop the runner:

1. Find the runner process:
   ```bash
   ps aux | grep runner.py
   ```

2. Kill it:
   ```bash
   kill <PID>
   ```

3. If that does not work, force kill:
   ```bash
   kill -9 <PID>
   ```

4. Also kill any lingering engine processes:
   ```bash
   pkill -f "engine/kalien"
   ```

On Windows:

```cmd
tasklist | findstr python
taskkill /F /PID <PID>

tasklist | findstr kalien
taskkill /F /PID <PID>
```

After a force kill, delete the state file to prevent a stale resume:

```bash
rm tapes/state.json
```

---

## How to Read Log Files

### runner.log

Each line is timestamped:

```
[2026-03-17T14:30:00] QUALIFY C252F0D5 (id=12345, w=32768, salts=0..0, 1200min left)
[2026-03-17T14:36:00]   salt 0/0 (w=32768, seed=C252F0D5)
[2026-03-17T14:42:00]   NEW BEST: 1205000 (salt=0x00000000)
[2026-03-17T14:42:00] DONE: C252F0D5 best=1,205,000 salt=0x00000000 w=32768 (360s)
```

Key patterns:
- `QUALIFY` / `PUSH` -- start of a new phase
- `salt N/M` -- progress within a phase
- `NEW BEST` -- new high score for this seed
- `DONE` -- phase completed successfully
- `EXPIRED` -- seed ran out of time
- `ABORTED` -- run stopped early
- `SUBMITTED` -- tape sent to API
- `API error` -- network issue (usually transient)
- `WARNING: engine exited with code N` -- engine crash on a specific salt

### Engine logs

Per-salt logs are in `tapes/<seed>/log_w<beam>_s<salt>.txt`. These contain the raw engine output, including frame-by-frame progress and the final score.

---

## How to Reset Everything

To start completely fresh:

```bash
rm -rf tapes/
```

This deletes:
- The seed database (kalien.db)
- All settings (settings.json, benchmark.json)
- All state files (state.json, seed_queue.txt)
- All tape files and engine logs
- All run history (results.tsv)

On next run, the runner will re-benchmark, create a fresh database, and prompt for configuration (if using `setup.sh`).

To reset only the database while keeping settings:

```bash
rm tapes/kalien.db tapes/state.json tapes/results.tsv
```

To reset only the benchmark (force re-calibration):

```bash
rm tapes/benchmark.json
```

Or use the `--benchmark` flag:

```bash
python3 runner.py --benchmark
```
