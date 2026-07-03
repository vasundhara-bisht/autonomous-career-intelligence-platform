"""Tests for operator scheduler soft pause (OHM Phase 5)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class OperatorSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._path = paths.ensure_data_dir() / ".test_operator_scheduler.json"
        if self._path.exists():
            self._path.unlink()

    def tearDown(self) -> None:
        if self._path.exists():
            self._path.unlink()

    def test_default_not_paused(self) -> None:
        from agent.operator_scheduler import is_scheduler_paused, load_operator_scheduler_state

        state = load_operator_scheduler_state(self._path)
        self.assertFalse(state["lifecycle_paused"])
        self.assertFalse(state["acquisition_paused"])
        self.assertFalse(is_scheduler_paused("lifecycle", path=self._path))

    def test_set_and_read_pause_flags(self) -> None:
        from agent.operator_scheduler import is_scheduler_paused, set_scheduler_paused

        set_scheduler_paused("lifecycle", True, path=self._path)
        self.assertTrue(is_scheduler_paused("lifecycle", path=self._path))
        self.assertFalse(is_scheduler_paused("acquisition", path=self._path))


if __name__ == "__main__":
    unittest.main()
