"""Tests for targeted SQLite orphan cleanup safety checks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for entry in (str(_REPO_ROOT), str(_SRC), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from cleanup_sqlite_orphan_job import (  # noqa: E402
    DEFAULT_ORPHAN_KEY,
    _key_present_in_csv_memory,
    cleanup_orphan_job,
)


class SqliteOrphanCleanupSafetyTests(unittest.TestCase):
    def test_default_orphan_key_constant(self) -> None:
        self.assertEqual(DEFAULT_ORPHAN_KEY, "v2:linkedin:4374896750")

    def test_refuses_when_key_in_historical_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "historical_jobs.csv"
            hist.write_text(
                "JOB_KEY_V2,title,company,ai_status\n"
                f"{DEFAULT_ORPHAN_KEY},PM,Acme,scored\n",
                encoding="utf-8",
            )
            jobs = Path(tmp) / "jobs.csv"
            jobs.write_text("JOB_KEY_V2,title,company\n", encoding="utf-8")

            with mock.patch(
                "cleanup_sqlite_orphan_job.paths.historical_jobs_csv",
                return_value=hist,
            ), mock.patch(
                "cleanup_sqlite_orphan_job.paths.jobs_csv",
                return_value=jobs,
            ):
                present, source = _key_present_in_csv_memory(DEFAULT_ORPHAN_KEY)
                self.assertTrue(present)
                self.assertEqual(source, "historical_jobs.csv")

                with self.assertRaises(RuntimeError):
                    cleanup_orphan_job(job_key_v2=DEFAULT_ORPHAN_KEY, dry_run=True)

    def test_absent_from_csv_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "historical_jobs.csv"
            hist.write_text(
                "JOB_KEY_V2,title,company,ai_status\n"
                "v2:other:1,PM,Acme,scored\n",
                encoding="utf-8",
            )
            jobs = Path(tmp) / "jobs.csv"
            jobs.write_text("JOB_KEY_V2,title,company\n", encoding="utf-8")

            with mock.patch(
                "cleanup_sqlite_orphan_job.paths.historical_jobs_csv",
                return_value=hist,
            ), mock.patch(
                "cleanup_sqlite_orphan_job.paths.jobs_csv",
                return_value=jobs,
            ):
                present, source = _key_present_in_csv_memory(DEFAULT_ORPHAN_KEY)
                self.assertFalse(present)
                self.assertEqual(source, "")


if __name__ == "__main__":
    unittest.main()
