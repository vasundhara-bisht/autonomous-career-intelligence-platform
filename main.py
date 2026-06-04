#!/usr/bin/env python3
"""Pipeline entrypoint shim. Run from repository root: python main.py"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for entry in (str(ROOT), str(ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

if __name__ == "__main__":
    runpy.run_module("agent.main", run_name="__main__")
