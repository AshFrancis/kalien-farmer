#!/usr/bin/env bash
#
# Kalien Farmer — Bootstrap Setup Script
#
# Detects platform, checks dependencies, builds the engine, and configures
# settings so you can start farming immediately.
#
# Usage:
#   ./setup.sh          # interactive setup
#   ./setup.sh --cpu    # force CPU-only build (skip GPU check)
#   ./setup.sh --gpu    # require GPU build (fail if CUDA missing)
#

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

ok()   { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${NC}  %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
info() { printf "${CYAN}[INFO]${NC}  %s\n" "$1"; }
step() { printf "\n${BOLD}--- %s ---${NC}\n" "$1"; }

# ── Parse Arguments ───────────────────────────────────────────────────

FORCE_CPU=0
FORCE_GPU=0
for arg in "$@"; do
    case "$arg" in
        --cpu) FORCE_CPU=1 ;;
        --gpu) FORCE_GPU=1 ;;
        --help|-h)
            echo "Usage: ./setup.sh [--cpu|--gpu]"
            echo "  --cpu    Force CPU-only build (skip GPU detection)"
            echo "  --gpu    Require GPU build (fail if CUDA not found)"
            exit 0
            ;;
        *)
            fail "Unknown argument: $arg"
            echo "Usage: ./setup.sh [--cpu|--gpu]"
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

errors=0

# ── Detect OS ─────────────────────────────────────────────────────────

step "Detecting platform"

case "$(uname -s)" in
    Darwin)
        OS="macos"
        ok "macOS detected ($(sw_vers -productVersion 2>/dev/null || echo 'unknown version'))"
        ;;
    Linux)
        OS="linux"
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            ok "Linux detected ($PRETTY_NAME)"
        else
            ok "Linux detected"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        OS="windows"
        ok "Windows (MSYS/MinGW) detected"
        ;;
    *)
        OS="unknown"
        warn "Unknown OS: $(uname -s) — will attempt build anyway"
        ;;
esac

# ── Check Python ──────────────────────────────────────────────────────

step "Checking Python"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo "0")
        minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON="$candidate"
            ok "Found $candidate $version"
            break
        else
            warn "$candidate version $version is too old (need 3.8+)"
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.8+ not found"
    case "$OS" in
        macos)  echo "  Install: brew install python3" ;;
        linux)  echo "  Install: sudo apt install python3  (or: sudo dnf install python3)" ;;
        windows) echo "  Install: Download from https://www.python.org/downloads/" ;;
    esac
    errors=$((errors + 1))
fi

# ── Check C++ Compiler ────────────────────────────────────────────────

step "Checking C++ compiler"

CXX_FOUND=""
if [ "$OS" = "windows" ]; then
    # On Windows, check for cl.exe
    if command -v cl &>/dev/null; then
        CXX_FOUND="cl"
        ok "Found MSVC (cl.exe)"
    fi
fi

if [ -z "$CXX_FOUND" ]; then
    for compiler in g++ clang++ c++; do
        if command -v "$compiler" &>/dev/null; then
            # Verify C++17 support
            tmpfile=$(mktemp /tmp/kalien_cxx_test.XXXXXX.cpp)
            cat > "$tmpfile" << 'CXXEOF'
#include <optional>
#include <string_view>
int main() { std::optional<int> x = 42; return x.value() - 42; }
CXXEOF
            if "$compiler" -std=c++17 -o /dev/null "$tmpfile" 2>/dev/null; then
                CXX_FOUND="$compiler"
                version=$("$compiler" --version 2>/dev/null | head -1)
                ok "Found $compiler ($version)"
                rm -f "$tmpfile"
                break
            else
                warn "$compiler found but C++17 support test failed"
            fi
            rm -f "$tmpfile"
        fi
    done
fi

if [ -z "$CXX_FOUND" ]; then
    fail "No C++17 compiler found"
    case "$OS" in
        macos)
            echo "  Install: xcode-select --install"
            echo "  This installs Apple Clang which supports C++17."
            ;;
        linux)
            echo "  Install: sudo apt install build-essential  (Debian/Ubuntu)"
            echo "           sudo dnf install gcc-c++           (Fedora/RHEL)"
            ;;
        windows)
            echo "  Install: Visual Studio Build Tools from"
            echo "           https://visualstudio.microsoft.com/visual-cpp-build-tools/"
            echo "  Select 'Desktop development with C++' workload."
            ;;
    esac
    errors=$((errors + 1))
fi

# ── Check GPU / CUDA ─────────────────────────────────────────────────

step "Checking GPU (optional)"

HAS_GPU=0
if [ "$FORCE_CPU" -eq 1 ]; then
    info "Skipping GPU check (--cpu flag)"
else
    if command -v nvidia-smi &>/dev/null; then
        gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        if [ -n "$gpu_name" ]; then
            ok "NVIDIA GPU found: $gpu_name"
            if command -v nvcc &>/dev/null; then
                nvcc_version=$(nvcc --version 2>/dev/null | grep "release" | sed 's/.*release //' | sed 's/,.*//')
                ok "CUDA toolkit found: $nvcc_version"
                HAS_GPU=1
            else
                warn "nvidia-smi found but nvcc (CUDA toolkit) not in PATH"
                echo "  GPU detected but CUDA compiler missing. Will build CPU-only."
                case "$OS" in
                    linux)  echo "  Install CUDA: https://developer.nvidia.com/cuda-downloads" ;;
                    windows) echo "  Install CUDA: https://developer.nvidia.com/cuda-downloads" ;;
                    macos)  echo "  Note: macOS does not support CUDA on recent hardware." ;;
                esac
            fi
        fi
    else
        info "No NVIDIA GPU detected — will build CPU-only engine"
    fi

    if [ "$FORCE_GPU" -eq 1 ] && [ "$HAS_GPU" -eq 0 ]; then
        fail "GPU build requested (--gpu) but CUDA not available"
        errors=$((errors + 1))
    fi
fi

# ── Stop on errors ────────────────────────────────────────────────────

if [ "$errors" -gt 0 ]; then
    echo ""
    fail "Setup cannot continue — $errors error(s) above need to be fixed."
    exit 1
fi

# ── Build Engine ──────────────────────────────────────────────────────

step "Building engine"

cd "$SCRIPT_DIR/engine"

if [ "$HAS_GPU" -eq 1 ] && [ "$FORCE_CPU" -eq 0 ]; then
    info "Building GPU engine (CUDA)..."
    if make clean 2>/dev/null; then true; fi
    if make 2>&1; then
        ok "GPU engine built successfully"
    else
        warn "GPU build failed — falling back to CPU build"
        HAS_GPU=0
        if make clean 2>/dev/null; then true; fi
        if make CPU=1 2>&1; then
            ok "CPU engine built successfully (GPU fallback)"
        else
            fail "Engine build failed"
            echo "  Check compiler output above for errors."
            exit 1
        fi
    fi
else
    info "Building CPU engine..."
    if make clean 2>/dev/null; then true; fi
    if make CPU=1 2>&1; then
        ok "CPU engine built successfully"
    else
        fail "Engine build failed"
        echo "  Check compiler output above for errors."
        exit 1
    fi
fi

# Verify binary exists
if [ "$OS" = "windows" ]; then
    BINARY="kalien.exe"
else
    BINARY="kalien"
fi

if [ -f "$SCRIPT_DIR/engine/$BINARY" ]; then
    ok "Engine binary: engine/$BINARY"
else
    fail "Engine binary not found after build"
    exit 1
fi

cd "$SCRIPT_DIR"

# ── Create tapes/ Directory ──────────────────────────────────────────

step "Setting up data directory"

mkdir -p "$SCRIPT_DIR/tapes"
ok "Created tapes/ directory"

# ── Configure Settings ────────────────────────────────────────────────

step "Configuration"

SETTINGS_FILE="$SCRIPT_DIR/tapes/settings.json"

if [ -f "$SETTINGS_FILE" ]; then
    info "Settings file already exists: tapes/settings.json"
    current_claimant=$(${PYTHON:-python3} -c "
import json
with open('$SETTINGS_FILE') as f:
    d = json.load(f)
print(d.get('claimant', 'not set'))
" 2>/dev/null || echo "not set")
    info "Current claimant: $current_claimant"
    echo ""
    read -rp "Update claimant address? [y/N] " update_claimant
    if [[ "$update_claimant" =~ ^[Yy] ]]; then
        echo ""
        echo "Enter your Stellar address (G... or C... format)."
        echo "This is where farming rewards will be sent."
        echo "Get one at https://kalien.xyz if you don't have one."
        echo ""
        read -rp "Claimant address: " CLAIMANT
        if [ -n "$CLAIMANT" ]; then
            ${PYTHON:-python3} -c "
import json
with open('$SETTINGS_FILE') as f:
    d = json.load(f)
d['claimant'] = '$CLAIMANT'
with open('$SETTINGS_FILE', 'w') as f:
    json.dump(d, f, indent=2)
"
            ok "Updated claimant address"
        fi
    fi
else
    echo ""
    echo "Enter your Stellar address (G... or C... format)."
    echo "This is where farming rewards will be sent."
    echo "Get one at https://kalien.xyz if you don't have one."
    echo "Press Enter to skip (you can set it later in tapes/settings.json)."
    echo ""
    read -rp "Claimant address: " CLAIMANT

    if [ -z "$CLAIMANT" ]; then
        CLAIMANT="YOUR_STELLAR_ADDRESS_HERE"
        warn "No address provided — edit tapes/settings.json before submitting"
    fi

    cat > "$SETTINGS_FILE" << EOF
{
  "claimant": "$CLAIMANT",
  "push_threshold": 1190000
}
EOF
    ok "Created tapes/settings.json"
fi

# ── Summary ───────────────────────────────────────────────────────────

step "Setup complete"

echo ""
printf "${GREEN}${BOLD}Kalien Farmer is ready.${NC}\n"
echo ""
echo "  Mode:    $([ "$HAS_GPU" -eq 1 ] && echo "GPU (CUDA)" || echo "CPU")"
echo "  Engine:  engine/$BINARY"
echo "  Data:    tapes/"
echo ""
printf "${BOLD}Next steps:${NC}\n"
echo ""
echo "  1. Start the dashboard:"
echo ""
printf "     ${CYAN}${PYTHON:-python3} kalien-farmer.py${NC}\n"
echo ""
echo "  2. Open http://localhost:8420 in your browser"
echo ""
echo "  3. Click START to begin farming"
echo ""
echo "  For standalone runner (no dashboard):"
echo ""
printf "     ${CYAN}${PYTHON:-python3} runner.py${NC}\n"
echo ""
echo "  For more information:"
echo "    docs/INSTALL.md       — detailed install instructions"
echo "    docs/OPERATIONS.md    — usage guide"
echo "    docs/CONFIG.md        — all configuration options"
echo ""
