# Architecture

## Component Overview

Kalien Farmer consists of three components:

| Component | File | Role |
|---|---|---|
| Dashboard | `kalien-farmer.py` | Web UI, runner lifecycle management, API proxy |
| Runner | `runner.py` | Beam search pipeline, seed fetching, tape submission |
| Engine | `engine/kalien` | C++/CUDA beam search binary |

The dashboard is optional. The runner can operate standalone. The engine is a compiled binary invoked as a subprocess.

### Dependencies

```
kalien-farmer.py
    |
    |  spawns subprocess
    v
runner.py
    |
    |  spawns subprocess (per salt)
    v
engine/kalien
```

Both Python scripts use only the standard library (no pip packages). The engine is a standalone C++ binary with no runtime dependencies beyond the OS and optionally CUDA.

---

## Data Flow

```
                    kalien.xyz API
                         |
                    GET /api/seed/current
                         |
                         v
                  +-------------+
                  |  runner.py  |
                  +------+------+
                         |
          +--------------+--------------+
          |              |              |
    fetch seed     run engine     submit tape
          |              |              |
          v              v              v
   tapes/kalien.db   engine/kalien   POST /api/proofs/jobs
          |              |
          |         writes tapes
          |              |
          v              v
   tapes/state.json  tapes/{seed}/*.tape
          |
          v
   tapes/results.tsv


                  +-------------------+
                  | kalien-farmer.py  |
                  +--------+----------+
                           |
              reads files + spawns runner.py
                           |
              +------------+------------+
              |            |            |
         kalien.db    state.json    seed_queue.txt
              |            |            |
              v            v            v
         /api/seeds   /api/status   /api/queue
              |
              v
         Browser (dashboard)
```

### Data stores

- **kalien.db** -- SQLite database. Source of truth for seed history, scores, and submission status. Written by runner, read by dashboard.
- **state.json** -- Current run in progress. Written atomically (write-to-tmp + rename) by runner after each salt. Enables crash recovery.
- **seed_queue.txt** -- Simple text file, one entry per line. Written by both dashboard (add seed) and runner (queue push after qualify). Protected by file lock.
- **settings.json** -- User configuration. Written by dashboard or setup script, read by runner.
- **benchmark.json** -- Hardware calibration results. Written by runner on first run.

---

## Runner State Machine

The runner processes seeds through a state machine with these phases:

```
                       +--------+
                       |  IDLE  |<--------------------------+
                       +---+----+                           |
                           |                                |
                    pop from queue                          |
                    or fetch from API                       |
                           |                                |
                           v                                |
                    +------------+                          |
                    |  QUALIFY   |                          |
                    | (1 salt)   |                          |
                    +------+-----+                          |
                           |                                |
               +-----------+-----------+                    |
               |                       |                    |
         score > threshold       score <= threshold         |
               |                       |                    |
               v                       v                    |
        +------------+          submit tape (if any)        |
        |    PUSH    |          record result                |
        | (30 salts) |                 |                    |
        +------+-----+                +--------------------+
               |
       +-------+-------+
       |               |
   completed       expired/aborted
       |               |
       v               v
  submit best     submit best so far
  record result   record result
       |               |
       +-------+-------+
               |
               v
            (back to IDLE)
```

### State transitions

| From | To | Trigger |
|---|---|---|
| Idle | Qualify | Queue entry popped, or current seed fetched from API |
| Qualify | Push | Qualify score exceeds `push_threshold` |
| Qualify | Idle | Qualify score below threshold (seed discarded) |
| Push | Idle | All salts completed |
| Push | Idle (aborted) | Seed expired mid-run (time remaining insufficient) |
| Any | Paused | `tapes/pause` file exists |
| Paused | Previous state | `tapes/pause` file deleted |

---

## Queue Format

Queue entries in `tapes/seed_queue.txt` use colon-delimited fields:

```
SEED_HEX:SEED_ID[:SALTS[:SALT_START[:BEAM]]]
```

| Field | Required | Description |
|---|---|---|
| `SEED_HEX` | Yes | 8-character uppercase hex seed |
| `SEED_ID` | Yes | Integer seed ID from the API |
| `SALTS` | No | Number of salts to run (default: 1 for qualify, 30 for push) |
| `SALT_START` | No | Starting salt index (default: 0) |
| `BEAM` | No | Beam width override. If greater than calibrated qualify beam, treated as a push run |

Examples:

```
C252F0D5:12345                      # qualify (1 salt, calibrated beam)
C252F0D5:12345:30:0:32768           # push (30 salts, beam=32768)
C252F0D5:12345:10:5:16384           # 10 salts starting at salt 5, beam=16384
```

Push runs (entries with beam > qualify_beam) are prioritized over qualify runs when popping from the queue.

---

## Database Schema

The SQLite database (`tapes/kalien.db`) has a single table:

```sql
CREATE TABLE IF NOT EXISTS seeds (
    -- Primary identification
    seed_hex TEXT PRIMARY KEY,          -- 8-char uppercase hex (e.g. "C252F0D5")
    seed_id INTEGER UNIQUE NOT NULL,   -- API seed ID (monotonically increasing)

    -- Qualify phase results
    qualify_score INTEGER DEFAULT 0,    -- Best score from qualify (1-salt) run
    qualify_salt TEXT DEFAULT '',        -- Salt that produced best qualify score (hex)
    qualify_elapsed INTEGER DEFAULT 0,  -- Qualify wall-clock time in seconds

    -- Push phase tracking
    push_status TEXT DEFAULT 'none',    -- none|queued|running|completed|expired
    push_beam INTEGER DEFAULT 0,       -- Beam width used for push
    push_score INTEGER DEFAULT 0,      -- Best score across all push salts
    push_salt TEXT DEFAULT '',          -- Salt that produced best push score (hex)
    push_salts_done INTEGER DEFAULT 0, -- Number of salts completed so far
    push_salts_total INTEGER DEFAULT 0,-- Total salts planned for push
    push_elapsed INTEGER DEFAULT 0,    -- Push wall-clock time in seconds

    -- Submission tracking
    submitted_score INTEGER DEFAULT 0, -- Score of the submitted tape
    submitted_job_id TEXT DEFAULT '',   -- API job ID for proof verification

    -- Metadata
    updated_at TEXT NOT NULL           -- ISO 8601 timestamp of last update
);
```

The database uses WAL journal mode for concurrent read/write access between the runner and dashboard.

---

## State File Format

`tapes/state.json` represents a run in progress. Written atomically after each salt.

```json
{
    "phase": "push",
    "seed": "C252F0D5",
    "seed_id": 12345,
    "beam": 32768,
    "salt_current": 5,
    "salt_start_orig": 0,
    "salt_end": 30,
    "best_score": 1205000,
    "best_salt": "0x00000003",
    "outdir": "/path/to/tapes/c252f0d5",
    "started": "2026-03-17T14:00:00",
    "elapsed": 3600,
    "aborted": null
}
```

| Field | Type | Description |
|---|---|---|
| `phase` | string | `"qualify"` or `"push"` |
| `seed` | string | Uppercase hex seed |
| `seed_id` | int | API seed ID |
| `beam` | int | Beam width for this run |
| `salt_current` | int | Next salt index to run (0-based) |
| `salt_start_orig` | int | Initial salt index (for resuming partial ranges) |
| `salt_end` | int | Salt index upper bound (exclusive) |
| `best_score` | int | Best score seen so far |
| `best_salt` | string | Salt hex that produced the best score |
| `outdir` | string | Absolute path to output directory |
| `started` | string | ISO 8601 start timestamp |
| `elapsed` | int | Wall-clock seconds (set on completion) |
| `aborted` | string/null | Reason for abort (e.g. `"expired"`) or null |

---

## Settings File Format

`tapes/settings.json`:

```json
{
    "claimant": "GABCDEF...",
    "push_threshold": 1190000
}
```

See [CONFIG.md](CONFIG.md) for full details on each field.

---

## Dashboard HTTP API

The dashboard serves a single-page HTML app and exposes a JSON API. All endpoints are on the same origin (no CORS).

### GET endpoints

| Path | Returns |
|---|---|
| `/` | HTML dashboard page |
| `/api/seeds` | Array of seed objects with scores, status, timing |
| `/api/queue` | Array of queue entries with estimated times |
| `/api/status` | Runner state, API connection status, queue length |
| `/api/stats` | Score history for charting (last 100 seeds) |
| `/api/runner` | Runner process status (running, paused, PID) |
| `/api/settings` | Current settings.json contents |
| `/api/tapes` | Array of tape files with scores and metadata |
| `/api/proofs` | Proof verification status for submitted seeds |

### POST endpoints

| Path | Body | Effect |
|---|---|---|
| `/api/start` | (empty) | Start the runner subprocess |
| `/api/stop` | (empty) | Stop the runner (SIGTERM) |
| `/api/pause` | (empty) | Create pause file |
| `/api/resume` | (empty) | Delete pause file |
| `/api/add_seed` | `{"seed":"HEX","seed_id":N,"beam":N,"salts":N}` | Add seed to front of queue |
| `/api/settings` | `{"push_threshold":N,...}` | Update settings.json |

---

## Tape File Naming

Tape files are written by the engine binary:

```
run_0x{salt_hex}_{score}.tape
```

Example: `run_0x00000003_1205000.tape`

- `salt_hex` -- the salt value in hex
- `score` -- the final game score

Engine log files follow a similar pattern:

```
log_w{beam}_s{salt}.txt
```

Example: `log_w32768_s3.txt`

---

## Benchmarking

On first run (or when hardware changes), the runner runs a calibration benchmark:

1. Run the engine with a fixed seed (`DEADBEEF`) at a test beam width (4096 GPU, 2048 CPU) for 1 salt
2. Measure wall-clock time
3. Extrapolate to find the maximum beam width that fits within time constraints:
   - Qualify: must complete 1 salt in under 9 minutes (540s)
   - Push: must complete 1 salt in under 8 minutes (480s), so 30 salts fit in 4 hours
4. Apply a 0.85x safety margin
5. For GPU: cap at VRAM limit (~63KB per beam unit)
6. Round down to nearest 1024
7. Save results to `tapes/benchmark.json`

The benchmark is re-run if hardware changes (different GPU, different CPU core count) or if `--benchmark` is passed.

---

## Submission Flow

1. After qualify or push completes, the runner scans the output directory for `.tape` files
2. Finds the tape with the highest score (parsed from filename)
3. Checks the database to see if a higher score was already submitted for this seed
4. If the new score is better, POSTs the tape binary to `POST /api/proofs/jobs?claimant=ADDR&seed_id=ID`
5. On success, records the job ID in the database
6. The dashboard polls `GET /api/proofs/jobs/{job_id}` to show proof status

---

## Failure Modes and Recovery

| Failure | Impact | Recovery |
|---|---|---|
| Engine crash (exit code != 0) | Current salt is skipped (-1 score) | Runner logs warning, continues to next salt |
| Runner crash | Current salt lost | Runner resumes from `state.json` on restart |
| Dashboard crash | No monitoring (runner continues) | Restart dashboard; runner is independent |
| API unreachable | Cannot fetch seeds or submit | Runner retries; uses 60s cache for seed API |
| Seed expired | Cannot submit tape | Runner detects expiry, marks seed as expired |
| Database locked | Transient error | 10-second timeout on SQLite connections |
| Disk full | Engine cannot write tapes | Engine fails, runner logs error |
| Queue corruption | Malformed entries skipped | Runner logs and continues to next entry |
