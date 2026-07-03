"""Tests for run_ai_refresh.py entry point."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class RunAiRefreshScriptTests(unittest.TestCase):
    def test_missing_openai_key_exits_nonzero(self) -> None:
        import importlib.util

        script = _REPO_ROOT / "scripts" / "run_ai_refresh.py"
        spec = importlib.util.spec_from_file_location("run_ai_refresh", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch.object(sys, "argv", ["run_ai_refresh.py", "--preset", "backlog"]):
                code = module.main()
        self.assertEqual(code, 1)

    def test_release_refresh_lock_unlinks_file(self) -> None:
        import importlib.util
        import tempfile

        script = _REPO_ROOT / "scripts" / "run_ai_refresh.py"
        spec = importlib.util.spec_from_file_location("run_ai_refresh", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(dir=_REPO_ROOT / "data") as tmp_dir:
            lock_path = Path(tmp_dir) / "ai-refresh.lock"
            with patch.object(module, "AI_REFRESH_LOCK", str(lock_path)):
                lock_fp = module._acquire_refresh_lock()
                self.assertIsNotNone(lock_fp)
                module._release_refresh_lock(lock_fp)
                self.assertFalse(lock_path.exists())

    def test_dry_run_writes_log(self) -> None:
        import importlib.util
        import tempfile

        script = _REPO_ROOT / "scripts" / "run_ai_refresh.py"
        spec = importlib.util.spec_from_file_location("run_ai_refresh", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory(dir=_REPO_ROOT / "data") as tmp_dir:
            lock_path = Path(tmp_dir) / "ai-refresh.lock"
            log_path = Path(tmp_dir) / "ai-refresh-test.log"
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "AI_REFRESH_LOG_FILE": str(log_path),
                },
                clear=False,
            ):
                with patch.object(module, "AI_REFRESH_LOCK", str(lock_path)):
                    with patch.object(module, "_acquisition_lock_held", return_value=False):
                        with patch.object(module, "ensure_database_ready"):
                            with patch.object(module, "get_read_session") as mock_session:
                                mock_session.return_value.__enter__.return_value = object()
                                with patch.object(
                                    module,
                                    "load_historical_jobs_view_df",
                                    return_value=__import__("pandas").DataFrame(),
                                ):
                                    with patch.object(
                                        module,
                                        "load_ai_refresh_cohort",
                                        return_value=([], 0),
                                    ):
                                        with patch.object(
                                            sys,
                                            "argv",
                                            [
                                                "run_ai_refresh.py",
                                                "--preset",
                                                "backlog",
                                                "--dry-run",
                                            ],
                                        ):
                                            code = module.main()
            self.assertEqual(code, 0)
            self.assertTrue(log_path.is_file())
            self.assertIn("Eligible with description", log_path.read_text(encoding="utf-8"))

    def test_finalize_uses_persisted_count(self) -> None:
        import importlib.util

        script = _REPO_ROOT / "scripts" / "run_ai_refresh.py"
        spec = importlib.util.spec_from_file_location("run_ai_refresh", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from db.services.ai_refresh_write import PersistRefreshResult

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            with patch.object(module, "_acquisition_lock_held", return_value=False):
                with patch.object(module, "_acquire_refresh_lock", return_value=object()):
                    with patch.object(module, "_release_refresh_lock"):
                        with patch.object(module, "ensure_database_ready"):
                            with patch.object(module, "get_read_session") as mock_session:
                                mock_session.return_value.__enter__.return_value = object()
                                with patch.object(
                                    module,
                                    "load_ai_refresh_cohort",
                                    return_value=([{"JOB_KEY_V2": "v2:test"}], 0),
                                ):
                                    with patch.object(module, "instrument_jobs_identity_v2"):
                                        with patch.object(module, "open_ai_refresh_run", return_value=7):
                                            with patch.object(
                                                module,
                                                "run_batch_ai_scoring",
                                            ) as mock_score:
                                                mock_score.return_value = type(
                                                    "R",
                                                    (),
                                                    {
                                                        "ai_scoring_jobs": [
                                                            {
                                                                "ai_status": "scored",
                                                                "score": 8,
                                                                "reason": "ok",
                                                            }
                                                        ],
                                                        "stats": type(
                                                            "S",
                                                            (),
                                                            {
                                                                "ai_skipped_by_cap": 0,
                                                                "batch_failures": 0,
                                                            },
                                                        )(),
                                                    },
                                                )()
                                                with patch.object(
                                                    module,
                                                    "persist_ai_refresh_scored_jobs",
                                                    return_value=PersistRefreshResult(
                                                        scoring_candidates=1,
                                                        persisted=1,
                                                        skipped=0,
                                                    ),
                                                ):
                                                    with patch.object(
                                                        module, "finalize_ai_refresh_run"
                                                    ) as mock_finalize:
                                                        with patch.object(
                                                            sys,
                                                            "argv",
                                                            [
                                                                "run_ai_refresh.py",
                                                                "--preset",
                                                                "discovery",
                                                            ],
                                                        ):
                                                            code = module.main()
        self.assertEqual(code, 0)
        mock_finalize.assert_called_once()
        self.assertEqual(mock_finalize.call_args.kwargs["scored_count"], 1)
        self.assertEqual(mock_finalize.call_args.kwargs["persist_skipped_count"], 0)


if __name__ == "__main__":
    unittest.main()
