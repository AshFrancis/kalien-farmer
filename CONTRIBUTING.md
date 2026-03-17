# Contributing to Kalien Farmer

## Getting Started

```bash
git clone <repo-url>
cd kalien-farmer
./setup.sh         # builds engine, creates settings
```

## Project Structure

```
kalien-farmer.py   # Web dashboard (HTTP server, process manager, embedded UI)
runner.py          # Beam search pipeline (benchmarking, queue, execution, submission)
engine/            # C++ beam search engine (GPU + CPU)
docs/              # Documentation suite
setup.sh           # Bootstrap script
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component design and data flow.

## Code Style

**Python:**
- Standard library only -- no external dependencies.
- Type hints on all function signatures (`from __future__ import annotations`).
- Use `Path` objects, not string paths.
- Follow existing section comment patterns (`# -- Section ---`).

**C++:**
- C++17 standard.
- `kernel.cu` for GPU code, `kernel.h` for CPU equivalent.
- Fixed-point arithmetic matches the game's Q12.4 / Q8.8 conventions.

## Making Changes

1. Create a branch for your change.
2. Verify both files compile: `python3 -c "import py_compile; py_compile.compile('runner.py', doraise=True); py_compile.compile('kalien-farmer.py', doraise=True)"`.
3. If you changed the engine, rebuild: `cd engine && make CPU=1`.
4. Test the full flow: start dashboard, click START, verify a seed gets qualified and submitted.
5. Keep commits focused. Separate engine changes from Python changes.

## Key Conventions

- **Queue format:** `SEED_HEX:SEED_ID[:SALTS[:SALT_START[:BEAM]]]` -- see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Tape naming:** `run_{salt}_{score}.tape` -- produced by the engine.
- **Settings:** `tapes/settings.json` -- see [docs/CONFIG.md](docs/CONFIG.md).
- **State files:** `tapes/state.json`, `tapes/status.txt`, `tapes/pause` -- see [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Reporting Issues

Open an issue with:
- OS and Python version
- GPU model (if applicable)
- Steps to reproduce
- Relevant log output from `tapes/runner.log`

## Engine Changes

The beam search engine in `engine/` has two parallel implementations:
- `kernel.cu` -- GPU (CUDA)
- `kernel.h` -- CPU (std::thread)

Changes to the search heuristics (greedy logic, fitness function, branch biases) must be mirrored in both files. The game simulation lives in `ports/sim.cuh` (GPU) and `ports/sim.h` (CPU).
