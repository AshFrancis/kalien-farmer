# Kalien Farmer

Automated beam search pipeline for [kalien.xyz](https://kalien.xyz) -- a ZK-proof blockchain game based on classic Asteroids. Finds optimal gameplay inputs, then submits cryptographic proofs to earn on-chain rewards.

<!-- ![Dashboard screenshot](docs/screenshot.png) -->

## Quick Start

```
git clone https://github.com/AshFrancis/kalien-farmer.git
cd kalien-farmer
python3 setup.py
python3 kalien-farmer.py
```

`setup.py` checks your system, builds the engine, and walks you through configuration. `kalien-farmer.py` opens a web dashboard on [localhost:8420](http://localhost:8420) -- click **START** to begin.

**Or download a prebuilt release** from the [Releases](https://github.com/AshFrancis/kalien-farmer/releases) page -- no Python or compiler needed.

## What Does Setup Do?

1. Checks for Python 3.8+ and a C++ compiler (tells you how to install if missing)
2. Detects NVIDIA GPU + CUDA (optional -- CPU works fine)
3. Builds the beam search engine for your platform
4. Asks for your Stellar address (to receive rewards)

## Requirements

- **Python 3.8+** (no pip packages needed -- stdlib only)
- **C++ compiler** -- Xcode (macOS), build-essential (Linux), or Visual Studio Build Tools (Windows)
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
