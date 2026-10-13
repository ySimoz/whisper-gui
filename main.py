#!/usr/bin/env python3
"""Launcher for Whisper GUI application with bundling support."""

import multiprocessing
import sys
from pathlib import Path

# Multiprocessing freeze support for packaged binaries
multiprocessing.freeze_support()

# Ensure src/ is on sys.path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from whisper_gui.main import main

if __name__ == "__main__":
    sys.exit(main())
