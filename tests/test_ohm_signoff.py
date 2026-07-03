"""Tests for OHM Phase 6 sign-off state."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class OhmSignoffTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._path = paths.ensure_data_dir() / ".test_ohm_signoff.json"
        if self._path.exists():
            self._path.unlink()

    def tearDown(self) -> None:
        if self._path.exists():
            self._path.unlink()

    def test_default_state_is_gated(self) -> None:
        from agent.ohm_signoff import is_lifecycle_resume_gated, load_ohm_signoff_state

        state = load_ohm_signoff_state(self._path)
        self.assertFalse(state["lifecycle_resume_approved"])
        self.assertTrue(is_lifecycle_resume_gated(path=self._path))

    def test_approve_ungates_resume(self) -> None:
        from agent.ohm_signoff import (
            approve_lifecycle_resume,
            is_lifecycle_resume_gated,
            lifecycle_resume_gate_reason,
            record_validation_ladder_passed,
        )

        self.assertIn("validation ladder", lifecycle_resume_gate_reason(path=self._path).lower())
        record_validation_ladder_passed(path=self._path)
        approve_lifecycle_resume(approved_by="Test Operator", path=self._path)
        self.assertFalse(is_lifecycle_resume_gated(path=self._path))
        self.assertEqual(lifecycle_resume_gate_reason(path=self._path), "")


if __name__ == "__main__":
    unittest.main()
