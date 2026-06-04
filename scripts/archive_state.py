#!/usr/bin/env python3
"""Write MANIFEST.json for archive_state.sh (checksums + schema snapshot)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.bootstrap_schema import derive_all_reset_schemas


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int | None:
    if path.suffix.lower() != ".csv":
        return None
    try:
        return len(pd.read_csv(path))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_dir", type=Path)
    args = parser.parse_args()
    archive_dir = args.archive_dir.resolve()

    git_head = ""
    try:
        git_head = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=_REPO_ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        pass

    files_meta = []
    for path in sorted(archive_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name == "MANIFEST.json":
            continue
        meta = {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        rc = _row_count(path)
        if rc is not None:
            meta["row_count"] = rc
        files_meta.append(meta)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "archive_dir": str(archive_dir),
        "schemas_at_archive": derive_all_reset_schemas(),
        "files": files_meta,
    }

    out = archive_dir / "MANIFEST.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
