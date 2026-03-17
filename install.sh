#!/bin/sh
# Kalien Farmer — One-line installer for macOS and Linux.
# Installs Python if missing, then runs setup.py.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/AshFrancis/kalien-farmer/main/install.sh | sh
#   or: ./install.sh (if already downloaded)

set -e

echo ""
echo "  Kalien Farmer Installer"
echo "  ======================"
echo ""

# ── Check/install Python ──────────────────────────────────────────────
install_python() {
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            echo "  [INFO] Installing Python via Homebrew..."
            if ! command -v brew >/dev/null 2>&1; then
                echo "  [INFO] Installing Homebrew first..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            fi
            brew install python3
            ;;
        Linux)
            echo "  [INFO] Installing Python..."
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y python3 build-essential
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y python3 gcc-c++ make
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -S --noconfirm python gcc make
            else
                echo "  [FAIL] Cannot detect package manager. Install Python 3.8+ manually."
                exit 1
            fi
            ;;
        *)
            echo "  [FAIL] Unsupported OS: $OS"
            exit 1
            ;;
    esac
}

PYTHON=""
for p in python3 python; do
    if command -v "$p" >/dev/null 2>&1; then
        # Check version >= 3.8
        ver=$("$p" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ] 2>/dev/null; then
            PYTHON="$p"
            echo "  [OK]   Python $ver ($p)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [WARN] Python 3.8+ not found"
    install_python
    # Re-check
    for p in python3 python; do
        if command -v "$p" >/dev/null 2>&1; then
            PYTHON="$p"
            break
        fi
    done
    if [ -z "$PYTHON" ]; then
        echo "  [FAIL] Python installation failed. Install manually and try again."
        exit 1
    fi
fi

# ── Check/install C++ compiler ────────────────────────────────────────
if ! command -v g++ >/dev/null 2>&1 && ! command -v clang++ >/dev/null 2>&1; then
    echo "  [WARN] No C++ compiler found"
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            echo "  [INFO] Installing Xcode command line tools..."
            xcode-select --install 2>/dev/null || true
            echo "  [INFO] If a dialog appeared, click Install and wait, then run this script again."
            exit 0
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get install -y build-essential
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y gcc-c++ make
            fi
            ;;
    esac
fi

# ── Clone repo if not in it ──────────────────────────────────────────
if [ ! -f "setup.py" ]; then
    if [ ! -d "kalien-farmer" ]; then
        echo ""
        echo "  [INFO] Downloading Kalien Farmer..."
        if command -v git >/dev/null 2>&1; then
            git clone https://github.com/AshFrancis/kalien-farmer.git
        else
            echo "  [INFO] git not found, downloading zip..."
            curl -fsSL -o kalien-farmer.zip https://github.com/AshFrancis/kalien-farmer/archive/refs/heads/main.zip
            unzip -q kalien-farmer.zip
            mv kalien-farmer-main kalien-farmer
            rm kalien-farmer.zip
        fi
    fi
    cd kalien-farmer
fi

# ── Run setup ────────────────────────────────────────────────────────
echo ""
"$PYTHON" setup.py "$@"
