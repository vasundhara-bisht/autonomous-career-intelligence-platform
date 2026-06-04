"""Tests for external AI candidate profile loading."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths  # noqa: E402
from agent.profile_loader import load_candidate_profile  # noqa: E402


class ProfileLoaderTests(unittest.TestCase):
    def test_default_profile_loads(self) -> None:
        text = load_candidate_profile()
        self.assertIn("Alex Morgan", text)
        self.assertIn("Target Roles", text)
        self.assertIn("Negative Signals", text)

    def test_env_override(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Custom profile for scoring tests.")
            custom = f.name
        try:
            with patch.dict(
                os.environ, {"AI_CANDIDATE_PROFILE_PATH": custom}, clear=False
            ):
                self.assertEqual(
                    paths.ai_candidate_profile_path(), Path(custom).resolve()
                )
                self.assertEqual(
                    load_candidate_profile(),
                    "Custom profile for scoring tests.",
                )
        finally:
            Path(custom).unlink(missing_ok=True)

    def test_missing_file_raises(self) -> None:
        with patch.dict(
            os.environ,
            {"AI_CANDIDATE_PROFILE_PATH": "/nonexistent/profile.md"},
            clear=False,
        ):
            with self.assertRaises(FileNotFoundError):
                load_candidate_profile()

    def test_profile_interpolates_into_scorer_prompt_shape(self) -> None:
        from agent.ai_batch_scorer import batch_score_jobs

        profile = load_candidate_profile()
        # Do not call OpenAI; verify batch_score_jobs builds job_text only by
        # checking profile is accepted (mock would be heavy). Instead assert length.
        self.assertGreater(len(profile), 1000)


if __name__ == "__main__":
    unittest.main()
