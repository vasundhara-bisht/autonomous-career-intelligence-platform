"""Unit tests for LinkedIn hiring-manager backfill script (no live Playwright)."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for entry in (str(_REPO_ROOT), str(_SRC), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from backfill_linkedin_hiring_managers import (  # noqa: E402
    _COHORT_SQL,
    _MANIFEST_VERSION,
    apply_job_update,
    derive_update_payload,
    load_manifest,
    run_apply_from_manifest,
    write_manifest,
)


class DeriveUpdatePayloadTests(unittest.TestCase):
    def test_valid_name(self) -> None:
        payload = derive_update_payload("Deblina Hait")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["hiring_manager"], "Deblina Hait")

    def test_skips_not_specified(self) -> None:
        self.assertIsNone(derive_update_payload("Not Specified"))

    def test_skips_blank(self) -> None:
        self.assertIsNone(derive_update_payload(""))

    def test_skips_unknown(self) -> None:
        self.assertIsNone(derive_update_payload("unknown"))


class ApplyJobUpdateTests(unittest.TestCase):
    def test_conditional_update_executes_with_guard(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute.return_value = result

        applied = apply_job_update(
            session,
            job_key_v2="v2:linkedin:1",
            payload={"hiring_manager": "Jane Recruiter"},
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
            job_key_v2="v2:linkedin:1",
            payload={"hiring_manager": "Jane Recruiter"},
            updated_at=datetime(2026, 6, 16, 12, 0, 0),
        )
        self.assertEqual(applied, 0)


class ManifestTests(unittest.TestCase):
    def _sample_doc(self) -> dict:
        return {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": "2026-06-17T20:00:00Z",
            "mode": "extract",
            "cohort_size": 1,
            "extraction_successes": 1,
            "extraction_failures": 0,
            "would_update": 1,
            "rows": [
                {
                    "job_key_v2": "v2:linkedin:4417376197",
                    "title": "Senior PM",
                    "company": "Learneo",
                    "extracted_hiring_manager": "Deblina Hait",
                    "url": "https://www.linkedin.com/jobs/view/4417376197/",
                }
            ],
        }

    def test_write_and_load_round_trip(self) -> None:
        path = Path(self._testMethodName) / "manifest.json"
        try:
            doc = self._sample_doc()
            written = write_manifest(doc, manifest_path=path)
            loaded = load_manifest(written)
            self.assertEqual(loaded["manifest_version"], _MANIFEST_VERSION)
            self.assertEqual(len(loaded["rows"]), 1)
            self.assertEqual(loaded["rows"][0]["extracted_hiring_manager"], "Deblina Hait")
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()

    def test_load_rejects_invalid_version(self) -> None:
        path = Path(self._testMethodName) / "bad.json"
        try:
            write_manifest({"manifest_version": 99, "rows": []}, manifest_path=path)
            with self.assertRaises(ValueError):
                load_manifest(path)
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()

    def test_load_rejects_invalid_hiring_manager(self) -> None:
        path = Path(self._testMethodName) / "bad_hm.json"
        try:
            doc = self._sample_doc()
            doc["rows"][0]["extracted_hiring_manager"] = "Not Specified"
            write_manifest(doc, manifest_path=path)
            with self.assertRaises(ValueError):
                load_manifest(path)
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()


class ApplyFromManifestTests(unittest.TestCase):
    def test_apply_from_manifest_updates_rows(self) -> None:
        manifest_dir = Path(self._testMethodName)
        manifest_path = manifest_dir / "recoverable.json"
        manifest_dir.mkdir(exist_ok=True)
        doc = {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": "2026-06-17T20:00:00Z",
            "mode": "extract",
            "cohort_size": 2,
            "extraction_successes": 2,
            "extraction_failures": 0,
            "would_update": 2,
            "rows": [
                {
                    "job_key_v2": "v2:linkedin:1",
                    "title": "PM",
                    "company": "A",
                    "extracted_hiring_manager": "Alice One",
                    "url": "https://www.linkedin.com/jobs/view/1/",
                },
                {
                    "job_key_v2": "v2:linkedin:2",
                    "title": "PM",
                    "company": "B",
                    "extracted_hiring_manager": "Bob Two",
                    "url": "https://www.linkedin.com/jobs/view/2/",
                },
            ],
        }
        write_manifest(doc, manifest_path=manifest_path)

        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = False

        with (
            patch("backfill_linkedin_hiring_managers.ensure_database_ready"),
            patch("backfill_linkedin_hiring_managers.get_session", return_value=session_cm),
            patch("backfill_linkedin_hiring_managers._sql_validation", return_value={"x": 1}),
            patch("backfill_linkedin_hiring_managers.apply_job_update", return_value=1) as mock_apply,
        ):
            rc = run_apply_from_manifest(manifest_path=manifest_path, limit=1)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_apply.call_count, 1)
        session.commit.assert_called_once()

        if manifest_dir.exists():
            for child in manifest_dir.iterdir():
                child.unlink()
            manifest_dir.rmdir()


class CohortSqlTests(unittest.TestCase):
    def test_cohort_filters_linkedin_hm_missing_no_recruiter_link(self) -> None:
        lowered = _COHORT_SQL.lower()
        self.assertIn("source = 'linkedin'", lowered)
        self.assertIn("not specified", lowered)
        self.assertIn("recruiter_job_links", lowered)
        self.assertIn("linkedin.com/jobs/view", lowered)
        self.assertIn("trim(j.link)", lowered)


if __name__ == "__main__":
    unittest.main()
