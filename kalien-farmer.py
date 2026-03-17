#!/usr/bin/env python3
"""Kalien Farmer — beam search pipeline with web dashboard.

Usage:
  python3 kalien-farmer.py              # start on localhost:8420
  python3 kalien-farmer.py --port 9000  # custom port
  python3 kalien-farmer.py --help       # show options
"""
from kalien.dashboard import main

if __name__ == "__main__":
    main()
