"""Unit tests for LinkedIn posted-date backfill script (no live Playwright)."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for entry in (str(_REPO_ROOT), str(_SRC), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from backfill_linkedin_posted_dates import (  # noqa: E402
    _COHORT_SQL,
    apply_job_update,
    derive_update_payload,
    write_manifest,
)

_ANCHOR = date(2026, 6, 16)


class DeriveUpdatePayloadTests(unittest.TestCase):
    def test_successful_relative_text(self) -> None:
        payload = derive_update_payload("2 hours ago", anchor_date=_ANCHOR)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["time_posted"], "2 hours ago")
        self.assertEqual(payload["posted_at_date"], "2026-06-16")
        self.assertEqual(payload["age_days"], 0)

    def test_skips_unknown(self) -> None:
        self.assertIsNone(derive_update_payload("Unknown", anchor_date=_ANCHOR))

    def test_skips_unparseable(self) -> None:
        self.assertIsNone(derive_update_payload("Recently", anchor_date=_ANCHOR))


class ApplyJobUpdateTests(unittest.TestCase):
    def test_conditional_update_executes_with_guard(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute.return_value = result

        applied = apply_job_update(
            session,
            job_key_v2="abc123",
            payload={
                "time_posted": "1 day ago",
                "posted_at_date": "2026-06-15",
                "age_days": 1,
            },
            updated_at=datetime(2026, 6, 16, 12, 0, 0),
        )
        self.assertEqual(applied, 1)
        session.execute.assert_called_once()

    def test_no_rows_updated_when_already_populated(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.rowcount = 0
        session.execute.return_value = result

        applied = apply_job_update(
            session,
            job_key_v2="abc123",
            payload={
                "time_posted": "1 day ago",
                "posted_at_date": "2026-06-15",
                "age_days": 1,
            },
            updated_at=datetime(2026, 6, 16, 12, 0, 0),
        )
        self.assertEqual(applied, 0)


class ManifestTests(unittest.TestCase):
    def test_write_manifest_creates_json(self) -> None:
        path = Path(self._testMethodName) / "manifest.json"
        try:
            written = write_manifest(
                [{"job_key_v2": "k1", "time_posted": "Unknown", "posted_at_date": None}],
                manifest_path=path,
            )
            self.assertTrue(written.is_file())
            data = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(data[0]["job_key_v2"], "k1")
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()


class CohortSqlTests(unittest.TestCase):
    def test_cohort_filters_linkedin_unknown_null_posted(self) -> None:
        lowered = _COHORT_SQL.lower()
        self.assertIn("source = 'linkedin'", lowered)
        self.assertIn("time_posted = 'unknown'", lowered)
        self.assertIn("posted_at_date is null", lowered)
        self.assertIn("trim(j.link)", lowered)


if __name__ == "__main__":
    unittest.main()
