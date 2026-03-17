#!/usr/bin/env python3
"""Kalien Farmer — Cross-platform setup script.

Works on macOS, Linux, and Windows. Checks dependencies, installs what it
can, builds the engine, and guides through first-run configuration.

Usage:
  python3 setup.py          # interactive setup
  python3 setup.py --cpu    # force CPU-only build
  python3 setup.py --auto   # non-interactive (skip claimant prompt)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPT_DIR / "engine"
TAPES_DIR = SCRIPT_DIR / "tapes"
SETTINGS_PATH = TAPES_DIR / "settings.json"

# ── Output helpers ────────────────────────────────────────────────────
GREEN = "\033[92m" if sys.stdout.isatty() else ""
RED = "\033[91m" if sys.stdout.isatty() else ""
YELLOW = "\033[93m" if sys.stdout.isatty() else ""
CYAN = "\033[96m" if sys.stdout.isatty() else ""
BOLD = "\033[1m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""

def ok(msg):    print(f"  {GREEN}[OK]{RESET}    {msg}")
def fail(msg):  print(f"  {RED}[FAIL]{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}[WARN]{RESET}  {msg}")
def info(msg):  print(f"  {CYAN}[INFO]{RESET}  {msg}")
def step(msg):  print(f"\n{BOLD}--- {msg} ---{RESET}")

def run(cmd, **kwargs):
    """Run a command, return (success, stdout)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kwargs)
        return r.returncode == 0, r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def main():
    force_cpu = "--cpu" in sys.argv
    auto_mode = "--auto" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    os_name = platform.system()  # Darwin, Linux, Windows
    os_label = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}.get(os_name, os_name)

    print(f"\n{BOLD}Kalien Farmer Setup{RESET}")
    print(f"  Platform: {os_label} ({platform.machine()})")
    print(f"  Python:   {sys.version.split()[0]}")

    errors = []

    # ── Step 1: Python version ────────────────────────────────────
    step("Checking Python")
    if sys.version_info >= (3, 8):
        ok(f"Python {sys.version.split()[0]}")
    else:
        fail(f"Python 3.8+ required, found {sys.version.split()[0]}")
        errors.append("python")

    # ── Step 2: C++ compiler ──────────────────────────────────────
    step("Checking C++ compiler")
    compiler = None
    if os_name == "Windows":
        # Check for cl.exe (MSVC)
        found, _ = run(["cl"], shell=True)
        if found:
            compiler = "cl"
            ok("MSVC (cl.exe)")
        else:
            # Check for g++ via MinGW/MSYS2
            found, _ = run(["g++", "--version"])
            if found:
                compiler = "g++"
                ok("g++ (MinGW/MSYS2)")
    else:
        for cxx in ["g++", "clang++", "c++"]:
            found, out = run([cxx, "--version"])
            if found:
                compiler = cxx
                ok(f"{cxx}")
                break

    if not compiler:
        fail("No C++ compiler found")
        if os_name == "Darwin":
            info("Install: xcode-select --install")
        elif os_name == "Linux":
            info("Install: sudo apt install build-essential  (Debian/Ubuntu)")
            info("    or:  sudo dnf install gcc-c++          (Fedora)")
        elif os_name == "Windows":
            info("Install Visual Studio Build Tools from:")
            info("  https://visualstudio.microsoft.com/visual-cpp-build-tools/")
            info("Or install MSYS2 with g++: https://www.msys2.org/")
        errors.append("compiler")

    # ── Step 3: Make ──────────────────────────────────────────────
    step("Checking build tools")
    make_cmd = None
    for m in ["make", "gmake", "mingw32-make"]:
        found, _ = run([m, "--version"])
        if found:
            make_cmd = m
            ok(f"{m}")
            break
    if not make_cmd:
        if os_name == "Windows":
            warn("'make' not found — will try direct compilation")
        else:
            fail("'make' not found")
            if os_name == "Darwin":
                info("Install: xcode-select --install")
            else:
                info("Install: sudo apt install make")
            errors.append("make")

    # ── Step 4: GPU (optional) ────────────────────────────────────
    step("Checking GPU")
    has_gpu = False
    if not force_cpu:
        found, out = run(["nvidia-smi", "--query-gpu=name,memory.total",
                          "--format=csv,noheader,nounits"])
        if found and out:
            gpu_name = out.split(",")[0].strip()
            has_gpu = True
            ok(f"NVIDIA GPU: {gpu_name}")
            # Check CUDA
            found_nvcc, nvcc_out = run(["nvcc", "--version"])
            if found_nvcc:
                ok("CUDA toolkit (nvcc)")
            else:
                warn("nvcc not found — will build CPU-only")
                info("For GPU support, install CUDA Toolkit: https://developer.nvidia.com/cuda-downloads")
                has_gpu = False
        else:
            info("No NVIDIA GPU detected — building CPU-only")
    else:
        info("Skipping GPU check (--cpu flag)")

    # ── Step 5: Build engine ──────────────────────────────────────
    step("Building engine")
    if errors:
        fail(f"Cannot build — fix the above issues first: {', '.join(errors)}")
    else:
        binary_name = "kalien.exe" if os_name == "Windows" else "kalien"
        binary_path = ENGINE_DIR / binary_name

        if binary_path.exists():
            ok(f"Engine already built ({binary_path.name})")
            info("To rebuild: delete engine/kalien and run setup again")
        else:
            build_gpu = has_gpu and not force_cpu

            if make_cmd:
                # Use Makefile
                cmd = [make_cmd]
                if not build_gpu:
                    cmd += ["CPU=1"]
                info(f"Running: {' '.join(cmd)} (in engine/)")
                result = subprocess.run(cmd, cwd=str(ENGINE_DIR))
                if result.returncode == 0 and binary_path.exists():
                    ok(f"Built {'GPU' if build_gpu else 'CPU'} engine")
                else:
                    fail("Build failed — check compiler output above")
                    errors.append("build")
            elif os_name == "Windows" and compiler == "cl":
                # Direct MSVC compile (no make)
                info("Building with MSVC directly...")
                cmd = ["cl", "/O2", "/DNDEBUG", "/EHsc", "/std:c++17",
                       "/DCPU_ONLY", "kalien.cpp", "/Fe:kalien.exe"]
                result = subprocess.run(cmd, cwd=str(ENGINE_DIR))
                if result.returncode == 0:
                    ok("Built CPU engine (MSVC)")
                else:
                    fail("Build failed")
                    errors.append("build")
            else:
                fail("No build method available")
                errors.append("build")

    # ── Step 6: Create data directory ─────────────────────────────
    step("Setting up data directory")
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    ok(f"Created {TAPES_DIR.relative_to(SCRIPT_DIR)}/")

    # ── Step 7: Configure claimant ────────────────────────────────
    step("Configuration")
    if SETTINGS_PATH.exists():
        import json
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
            claimant = settings.get("claimant", "")
            if claimant and claimant not in ("", "YOUR_STELLAR_ADDRESS_HERE"):
                ok(f"Claimant: {claimant[:8]}...{claimant[-4:]}")
            else:
                warn("Claimant not configured yet")
                _prompt_claimant(auto_mode)
        except Exception:
            _prompt_claimant(auto_mode)
    else:
        _prompt_claimant(auto_mode)

    # ── Done ──────────────────────────────────────────────────────
    print()
    if errors:
        print(f"{RED}{BOLD}Setup incomplete — fix the issues above and run again.{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}Setup complete!{RESET}")
        print()
        print(f"  Start farming:")
        print(f"    {CYAN}python3 kalien-farmer.py{RESET}")
        print()
        print(f"  This opens the web dashboard. Click START to begin.")
        print(f"  Your browser will open to http://localhost:8420")
        print()


def _prompt_claimant(auto_mode):
    """Prompt for Stellar claimant address."""
    import json

    if auto_mode:
        info("Skipping claimant setup (--auto mode)")
        info("Configure later in the dashboard Setup tab or tapes/settings.json")
        _write_settings("")
        return

    print()
    info("Your Stellar address is needed to receive rewards.")
    info("It starts with G (public key) or C (contract address), 56 characters.")
    print()

    try:
        addr = input(f"  {BOLD}Stellar address:{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        addr = ""

    if addr and len(addr) == 56 and addr[0] in "GC":
        _write_settings(addr)
        ok(f"Saved: {addr[:8]}...{addr[-4:]}")
    elif addr:
        warn(f"Address looks invalid (expected 56 chars starting with G or C)")
        _write_settings(addr)
        info("You can fix it later in the dashboard Setup tab")
    else:
        info("Skipped — configure later in the dashboard Setup tab")
        _write_settings("")


def _write_settings(claimant):
    import json
    settings = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    settings["claimant"] = claimant
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


if __name__ == "__main__":
    main()
