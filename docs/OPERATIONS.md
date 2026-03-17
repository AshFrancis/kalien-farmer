# Operations Guide

## Starting and Stopping

### Start the dashboard (recommended)

```bash
python3 kalien-farmer.py
```

This starts the web dashboard on [http://localhost:8420](http://localhost:8420) and opens your browser. Click **START** in the dashboard to begin the runner.

### Start the runner directly (no dashboard)

```bash
python3 runner.py
```

The runner fetches seeds from the kalien.xyz API, runs beam search, and submits tapes automatically. It runs until interrupted with Ctrl+C.

### Stop

**From the dashboard:** Click **STOP**. The runner finishes the current salt and exits. State is saved for resume.

**From the terminal:** Press Ctrl+C. The runner catches SIGTERM and exits cleanly.

**Force stop (runner won't exit):**

```bash
# Find the process
ps aux | grep runner.py

# Kill it
kill <PID>

# Or force kill
kill -9 <PID>
```

On Windows:

```cmd
tasklist | findstr python
taskkill /F /PID <PID>
```

---

## Pause and Resume

**Pause:** Click **PAUSE** in the dashboard, or create the pause file manually:

```bash
touch tapes/pause
```

The runner finishes the current salt, then waits. No work is lost.

**Resume:** Click **RESUME** in the dashboard, or delete the pause file:

```bash
rm tapes/pause
```

---

## Dashboard Controls

The dashboard (port 8420) has four tabs:

### SEEDS

Shows all seeds that have been processed, with:
- Qualify score (1-salt quick test)
- Push status and score (30-salt deep run)
- Submission status and proof verification
- Replay links on kalien.xyz
- Time remaining before seed expires

### QUEUE

Shows pending work items in order. Push runs (high beam width) are prioritized over qualify runs. Each entry shows estimated time.

### TAPES

Lists all generated tape files with scores, grouped by seed. Sorted by modification time.

### SETTINGS

Change the push threshold. Seeds scoring above this threshold during qualification are promoted to a full push run.

---

## Adding Priority Seeds

From the dashboard, use the "Add Seed" form. Provide:
- Seed hex (8 characters, e.g., `C252F0D5`)
- Seed ID (from the API)
- Beam width (optional, defaults to calibrated push beam)
- Salt count (optional, defaults to 30)

The seed is added to the front of the queue.

From the command line, append to the queue file directly:

```bash
echo "C252F0D5:12345:30:0:32768" >> tapes/seed_queue.txt
```

Format: `SEED_HEX:SEED_ID:SALTS:SALT_START:BEAM`

---

## Changing Settings

Edit `tapes/settings.json` directly, or use the dashboard Settings tab.

Key settings:
- `claimant` -- Stellar address for reward submission
- `push_threshold` -- minimum qualify score to trigger a push run (default: 1,190,000)

Changes take effect on the next seed (the runner re-reads settings.json between seeds).

---

## Monitoring Progress

### Dashboard

The dashboard auto-refreshes every 3 seconds. The header shows:
- Runner status (running/stopped/paused)
- API connection status
- Current seed from the API

The SEEDS tab shows live progress for the running seed, including current salt number and best score so far.

### Log file

The runner writes to `tapes/runner.log`. Tail it for real-time output:

```bash
tail -f tapes/runner.log
```

### Status file

`tapes/status.txt` contains a one-line summary updated after each salt:

```
running C252F0D5 2026-03-17T14:30:00 push w=32768 salt=5/29
```

### Results history

`tapes/results.tsv` is a tab-separated log of every completed run:

```
timestamp	seed	seed_id	best_score	best_salt	salts	elapsed	beam
2026-03-17T14:30:00	C252F0D5	12345	1205000	0x00000003	30	7200s	w32768
```

---

## Understanding the Pipeline

```
                                                     no
Seed from API --> Qualify (1 salt, ~6-9 min) ---------> discard
                        |
                        | score > push_threshold
                        v
                  Push (30 salts, ~2-4 hrs)
                        |
                        v
                  Submit best tape to API
                        |
                        v
                  Proof verification (ZK prover)
                        |
                        v
                  On-chain claim
```

### Qualify

A single-salt run at the calibrated beam width. This is a quick screen to see if the seed is worth investing more compute. If the score exceeds `push_threshold`, the seed is promoted to push.

The best tape from qualification is also submitted (in case it already beats existing submissions).

### Push

30 salts at the calibrated beam width. Each salt uses a different RNG perturbation, producing a different search trajectory. The best tape across all salts is submitted.

Every 5 salts, the runner checks whether the seed has expired. If time is running out, the push is aborted and the best tape so far is submitted.

### Submit

The best tape is POSTed to the kalien.xyz proof API. A ZK prover verifies the tape, then an on-chain claim is made. The dashboard shows proof status progression: queued, proving, succeeded.

---

## Recovery

### What happens on crash

The runner saves state to `tapes/state.json` after every salt. On restart, it detects the interrupted run and resumes from the last completed salt.

### What gets lost on crash

Only the salt that was running at the time of the crash. All previously completed salts and their tapes are preserved.

### Manual recovery

If the state file is corrupted, delete it to start fresh:

```bash
rm tapes/state.json
```

The runner will skip the interrupted run and move to the next seed.

### Clearing everything

To reset all data and start from scratch:

```bash
rm -rf tapes/
```

The `tapes/` directory and all its contents (database, settings, state, tapes) will be recreated on next run. You will need to re-enter your claimant address.

---

## Multi-Device Setup

You can run Kalien Farmer on multiple machines. Each machine independently:
- Fetches seeds from the API
- Runs beam search
- Submits tapes

No coordination is needed. The API accepts the best tape for each seed regardless of which machine submitted it.

Each machine should have its own `tapes/` directory with its own `settings.json` pointing to the same claimant address.

---

## Log Files and Data

All runtime data lives in `tapes/`:

| File | Purpose |
|---|---|
| `kalien.db` | SQLite database of all seeds and their scores |
| `settings.json` | User configuration (claimant, thresholds) |
| `benchmark.json` | Hardware calibration (beam widths, timing) |
| `state.json` | Current run state (for crash recovery) |
| `seed_queue.txt` | Pending work queue |
| `status.txt` | One-line runner status |
| `runner.log` | Full runner log |
| `results.tsv` | Completed run history |
| `pause` | Pause signal file (exists = paused) |
| `seed_queue.txt.lock` | Queue file lock |

### Per-seed directories

Each seed gets a subdirectory under `tapes/`:

```
tapes/c252f0d5/
  run_0x00000000_1205000.tape    # tape file (salt_score.tape)
  log_w32768_s0.txt              # engine output for salt 0
  log_w32768_s1.txt              # engine output for salt 1
  ...
```

Tape filenames encode the salt and final score for easy identification.
