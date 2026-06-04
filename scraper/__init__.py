"""Multi-source job acquisition scrapers."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for entry in (str(_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
