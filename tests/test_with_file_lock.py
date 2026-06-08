"""Tests for scripts/scheduling/with_file_lock.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCK_SCRIPT = _REPO_ROOT / "scripts" / "scheduling" / "with_file_lock.py"


class WithFileLockTests(unittest.TestCase):
    def _run(
        self,
        lock_file: str,
        *extra_args: str,
        skip_exit: int | None = None,
        skip_message: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(_LOCK_SCRIPT), "--lock-file", lock_file]
        if skip_exit is not None:
            cmd.extend(["--skip-exit", str(skip_exit)])
        if skip_message is not None:
            cmd.extend(["--skip-message", skip_message])
        cmd.append("--")
        cmd.extend(extra_args)
        return subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_runs_command_when_lock_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = str(Path(tmp) / "test.lock")
            marker = Path(tmp) / "ran.txt"
            proc = self._run(
                lock, sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(marker.is_file())

    def test_busy_skips_without_running_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = str(Path(tmp) / "busy.lock")
            marker = Path(tmp) / "should_not_run.txt"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    str(_LOCK_SCRIPT),
                    "--lock-file",
                    lock,
                    "--",
                    sys.executable,
                    "-c",
                    "import time; time.sleep(3)",
                ],
                cwd=_REPO_ROOT,
            )
            try:
                time.sleep(0.2)
                proc = self._run(
                    lock,
                    sys.executable,
                    "-c",
                    f"open({str(marker)!r}, 'w').close()",
                    skip_exit=0,
                    skip_message="SKIP: held",
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("SKIP: held", proc.stdout)
                self.assertFalse(marker.exists())
            finally:
                holder.wait(timeout=10)

    def test_busy_can_use_nonzero_skip_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = str(Path(tmp) / "busy2.lock")
            holder = subprocess.Popen(
                [
                    sys.executable,
                    str(_LOCK_SCRIPT),
                    "--lock-file",
                    lock,
                    "--",
                    sys.executable,
                    "-c",
                    "import time; time.sleep(3)",
                ],
                cwd=_REPO_ROOT,
            )
            try:
                time.sleep(0.2)
                proc = self._run(
                    lock,
                    sys.executable,
                    "-c",
                    "pass",
                    skip_exit=42,
                )
                self.assertEqual(proc.returncode, 42, proc.stderr)
            finally:
                holder.wait(timeout=10)

    def test_requires_command_after_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = str(Path(tmp) / "bad.lock")
            proc = subprocess.run(
                [sys.executable, str(_LOCK_SCRIPT), "--lock-file", lock],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
