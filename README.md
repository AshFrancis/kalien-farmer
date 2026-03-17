# Kalien Farmer

Automated beam search pipeline for [kalien.xyz](https://kalien.xyz) -- a ZK-proof blockchain game based on classic Asteroids. Finds optimal gameplay inputs, then submits cryptographic proofs to earn on-chain rewards.

<!-- ![Dashboard screenshot](docs/screenshot.png) -->

## Quick Start

**Already downloaded?** Just run:
```
python3 setup.py && python3 kalien-farmer.py
```

**From scratch (one line):**

macOS / Linux:
```bash
curl -fsSL https://raw.githubusercontent.com/AshFrancis/kalien-farmer/main/install.sh | sh
```

Windows — download and double-click `install.bat`, or:
```powershell
git clone https://github.com/AshFrancis/kalien-farmer.git; cd kalien-farmer; python setup.py; python kalien-farmer.py
```

The installer handles everything: checks for Python, installs a C++ compiler if needed, builds the engine, and walks you through configuration. The farmer opens a web dashboard on [localhost:8420](http://localhost:8420) -- click **START** to begin.

## What Does Setup Do?

1. Checks for Python 3.8+ (installs it if missing on macOS/Linux)
2. Checks for a C++ compiler (tells you exactly how to install one)
3. Detects NVIDIA GPU + CUDA (optional -- CPU works fine)
4. Builds the beam search engine
5. Asks for your Stellar address (to receive rewards)

If anything is missing, it gives you the exact command to fix it for your OS.

## Requirements

- **Python 3.8+** (no pip packages needed -- stdlib only)
- **C++ compiler** -- comes with Xcode (macOS), build-essential (Linux), or Visual Studio Build Tools (Windows)
- **Optional:** NVIDIA GPU with CUDA 12.x for faster search

## Documentation

| Document | Contents |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | OS-specific setup (macOS, Linux, Windows, GPU) |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Starting, stopping, monitoring, recovery |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component design, data flow, state machines |
| [docs/CONFIG.md](docs/CONFIG.md) | Every setting, CLI argument, and config format |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems and solutions |
| [docs/SECURITY.md](docs/SECURITY.md) | Network exposure, data handling |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Build, test, and contribute |

## License

[MIT](LICENSE)
