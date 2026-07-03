#!/usr/bin/env python3
"""Non-blocking probe for an advisory file lock (Scheduler B acquisition overlap guard)."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys


def probe_lock_available(lock_file: str) -> bool:
    """Return True when the lock file is not held by another process."""
    lock_path = os.path.abspath(lock_file)
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)

    lock_fp = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        lock_fp.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe whether a file lock is currently held.")
    parser.add_argument("--lock-file", required=True)
    parser.add_argument(
        "--skip-message",
        default="",
        help="Printed to stdout when the lock is busy.",
    )
    args = parser.parse_args(argv)

    if probe_lock_available(args.lock_file):
        return 0

    if args.skip_message:
        print(args.skip_message, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
