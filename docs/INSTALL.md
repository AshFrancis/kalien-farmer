# Installation

## Quick Path

Run `./setup.sh` from the project root. It detects your OS, checks dependencies, builds the engine, and writes initial configuration. The rest of this document covers manual setup for each platform.

## Requirements

- **Python 3.8+** (standard library only, no pip packages)
- **C++17 compiler** (GCC 7+, Clang 5+, or MSVC 2017+)
- **GNU Make** (or compatible)
- **Optional:** NVIDIA GPU with CUDA 12.x toolkit for GPU-accelerated beam search

---

## macOS

### 1. Install Xcode command line tools

```bash
xcode-select --install
```

This provides Apple Clang (C++17 capable) and Make.

### 2. Install Python 3 (if not already present)

macOS ships with Python 3 on recent versions. Verify:

```bash
python3 --version
```

If missing, install via Homebrew:

```bash
brew install python3
```

### 3. Build the engine

```bash
cd engine
make CPU=1
```

macOS does not support CUDA on Apple Silicon or recent Intel Macs, so CPU-only is the standard path.

### 4. Verify

```bash
./kalien --help
```

You should see usage output with `--seed`, `--beam`, etc.

---

## Ubuntu / Debian

### 1. Install build tools and Python

```bash
sudo apt update
sudo apt install build-essential python3
```

### 2. Build the engine

**CPU only:**

```bash
cd engine
make CPU=1
```

**GPU (requires CUDA toolkit):**

```bash
cd engine
make
```

The Makefile auto-detects your GPU compute capability via `nvidia-smi`.

### 3. Verify

```bash
./kalien --help
```

---

## Fedora / RHEL

### 1. Install build tools and Python

```bash
sudo dnf install gcc-c++ make python3
```

### 2. Build the engine

```bash
cd engine
make CPU=1
```

### 3. Verify

```bash
./kalien --help
```

---

## Windows

### 1. Install Visual Studio Build Tools

Download from [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/). Select the **Desktop development with C++** workload.

### 2. Install Python

Download from [python.org](https://www.python.org/downloads/). Ensure "Add Python to PATH" is checked during install.

### 3. Install GNU Make

Install via [chocolatey](https://chocolatey.org/):

```cmd
choco install make
```

Or use the Make that ships with Git for Windows / MSYS2.

### 4. Build the engine

Open a **Developer Command Prompt for VS** (or x64 Native Tools Command Prompt):

**CPU only:**

```cmd
cd engine
make CPU=1
```

**GPU (requires CUDA 12.x):**

```cmd
cd engine
make
```

### 5. Makefile paths

The Windows section of `engine/Makefile` has hardcoded paths for Visual Studio, the Windows SDK, and CUDA. If your installation differs from the defaults, edit these variables at the top of the Windows block:

- `VS_PATH` -- path to MSVC tools
- `WINSDK_INC` -- Windows SDK include path
- `WINSDK_LIB` -- Windows SDK library path
- `GPU_INCLUDE` -- CUDA include path
- `GPU_LIB` -- CUDA library path

### 6. Verify

```cmd
engine\kalien.exe --help
```

---

## GPU Setup (CUDA)

GPU acceleration requires an NVIDIA GPU and the CUDA toolkit.

### 1. Install CUDA Toolkit

Download from [NVIDIA CUDA Downloads](https://developer.nvidia.com/cuda-downloads). Version 12.x is required.

Verify installation:

```bash
nvcc --version
nvidia-smi
```

### 2. Check compute capability

The Makefile auto-detects your GPU architecture. To check manually:

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

### 3. Build with GPU support

```bash
cd engine
make
```

If the GPU build fails, you can always fall back to CPU:

```bash
make clean
make CPU=1
```

### 4. Linux: compiler compatibility

CUDA 12.x requires a compatible host compiler. If your default `g++` is too new, specify an older version:

```bash
CXX=g++-12 make
```

---

## Manual Build Reference

The engine Makefile supports three configurations:

| Command | Platform | Mode |
|---|---|---|
| `make CPU=1` | Linux / macOS | CPU only (C++17) |
| `make` | Linux / macOS | GPU (CUDA + C++17) |
| `make CPU=1` | Windows (MSVC) | CPU only |
| `make` | Windows (MSVC + CUDA) | GPU |

Build output is `kalien` (Unix) or `kalien.exe` (Windows) in the `engine/` directory.

Clean build artifacts:

```bash
cd engine
make clean
```

---

## Verification Checklist

After setup, verify everything works:

1. **Engine binary exists:**
   ```bash
   ls engine/kalien    # or engine/kalien.exe on Windows
   ```

2. **Engine runs:**
   ```bash
   engine/kalien --help
   ```

3. **Python version:**
   ```bash
   python3 --version   # should be 3.8+
   ```

4. **Dashboard starts:**
   ```bash
   python3 kalien-farmer.py --no-browser
   # Should print "Serving on http://127.0.0.1:8420"
   # Ctrl+C to stop
   ```

5. **Runner starts (optional, quick test):**
   ```bash
   python3 runner.py --benchmark
   # Runs a ~60s benchmark and prints calibrated beam widths
   # Ctrl+C to stop after benchmark completes
   ```
