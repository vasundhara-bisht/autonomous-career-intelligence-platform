"""Career intelligence pipeline package."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPO_ROOT / "src"

for entry in (str(REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
