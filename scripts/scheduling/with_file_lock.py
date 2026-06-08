#!/usr/bin/env python3
"""
Acquire an exclusive advisory file lock (fcntl) and run a subprocess.

Used by scheduled acquisition/backup wrappers on macOS where flock(1) is absent.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys


def _parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run COMMAND under an exclusive non-blocking file lock."
    )
    parser.add_argument("--lock-file", required=True, help="Path to lock file")
    parser.add_argument(
        "--skip-exit",
        type=int,
        default=0,
        help="Exit code when lock is held by another process (default: 0)",
    )
    parser.add_argument(
        "--skip-message",
        default="",
        help="Message printed to stdout when lock is busy",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory for COMMAND (default: inherit)",
    )
    args, remainder = parser.parse_known_args(argv)
    if not remainder or remainder[0] != "--":
        parser.error("usage: with_file_lock.py [options] -- COMMAND [ARGS...]")
    command = remainder[1:]
    if not command:
        parser.error("COMMAND required after --")
    return args, command


def main(argv: list[str] | None = None) -> int:
    args, command = _parse_args(argv)
    lock_path = os.path.abspath(args.lock_file)
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)

    lock_fp = None
    try:
        lock_fp = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.skip_message:
                print(args.skip_message, flush=True)
            return int(args.skip_exit)

        lock_fp.seek(0)
        lock_fp.truncate()
        lock_fp.write(f"{os.getpid()}\n")
        lock_fp.flush()

        result = subprocess.run(
            command,
            cwd=args.cwd,
            env=os.environ.copy(),
            check=False,
        )
        return int(result.returncode)
    except OSError as exc:
        print(
            f"ERROR: failed to acquire lock on {lock_path}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if lock_fp is not None:
            lock_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
