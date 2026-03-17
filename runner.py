#!/usr/bin/env python3
"""Kalien Runner — beam search pipeline with auto-submission.

Usage:
  python3 runner.py                    # auto-detect everything
  python3 runner.py --level low        # 50% resources
  python3 runner.py --benchmark        # force re-benchmark
  python3 runner.py --help             # show options
"""
from kalien.runner import main

if __name__ == "__main__":
    main()
