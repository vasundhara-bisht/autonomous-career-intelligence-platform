"""Unit tests for V2-primary historical_jobs.csv persistence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.historical_persistence import (  # noqa: E402
    generate_job_key,
    update_historical_jobs,
)
from db.services.parity_checks import (  # noqa: E402
    check_historical_v2_uniqueness,
    check_jobs_csv_subset_of_historical,
)


def _job(
    *,
    v2: str,
    title: str = "Product Manager II",
    company: str = "Razorpaysoftwareprivatelimited",
    score: float = 6.0,
) -> dict:
    job = {
        "JOB_KEY_V2": v2,
        "normalized_title": title.lower(),
        "normalized_company": company.lower(),
        "title": title,
        "company": company,
        "location": "Bengaluru",
        "source": "greenhouse",
        "link": f"https://example.com/{v2}",
        "ai_score": score,
        "ai_status": "scored",
        "reason": "test",
        "hiring_manager": "Not Specified",
    }
    job["JOB_KEY"] = generate_job_key(job)
    return job


class HistoricalPersistenceV2PrimaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.historical_path = Path(self._tmpdir.name) / "historical_jobs.csv"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _patch_historical_path(self):
        return patch(
            "agent.historical_persistence.paths.historical_jobs_csv",
            return_value=self.historical_path,
        )

    def test_same_legacy_key_distinct_v2_persist_as_separate_rows(self) -> None:
        v2_a = "v2:greenhouse:razorpaysoftwareprivatelimited:4684210005"
        v2_b = "v2:greenhouse:razorpaysoftwareprivatelimited:4688605005"
        v2_c = "v2:greenhouse:razorpaysoftwareprivatelimited:4699228005"

        seed = pd.DataFrame(
            [
                {
                    "JOB_KEY": generate_job_key(_job(v2=v2_c)),
                    "JOB_KEY_V2": v2_c,
                    "title": "Product Manager II",
                    "company": "Razorpaysoftwareprivatelimited",
                    "location": "Bengaluru",
                    "source": "greenhouse",
                    "link": "https://old.example/4699228005",
                    "ai_score": 5.0,
                    "ai_status": "scored",
                    "reason": "old",
                    "hiring_manager": "Not Specified",
                    "first_seen": "2026-01-01 10:00:00",
                    "last_seen": "2026-01-01 10:00:00",
                    "times_seen": 3,
                    "currently_active": True,
                    "applied": False,
                    "rejected": False,
                    "interview": False,
                    "offer": False,
                    "notes": "",
                    "posted_at_date": "",
                    "age_days": "",
                }
            ]
        )
        seed.to_csv(self.historical_path, index=False)

        with self._patch_historical_path():
            update_historical_jobs(
                [
                    _job(v2=v2_a, score=6.0),
                    _job(v2=v2_b, score=7.0),
                    _job(v2=v2_c, score=8.0),
                ]
            )

        result = pd.read_csv(self.historical_path, dtype=str, keep_default_na=False)
        v2_values = set(result["JOB_KEY_V2"].astype(str).str.strip())

        self.assertIn(v2_a, v2_values)
        self.assertIn(v2_b, v2_values)
        self.assertIn(v2_c, v2_values)
        self.assertEqual(len(v2_values), 3)

        legacy_keys = result["JOB_KEY"].astype(str).tolist()
        self.assertEqual(
            legacy_keys.count("product manager ii::razorpaysoftwareprivatelimited"),
            3,
        )

        parity = check_historical_v2_uniqueness(result)
        self.assertTrue(parity.ok(), parity.failures)

    def test_refresh_preserves_first_seen_and_updates_last_seen(self) -> None:
        v2 = "v2:greenhouse:examplecorp:111"
        first_seen = "2026-01-01 09:00:00"
        seed = pd.DataFrame(
            [
                {
                    "JOB_KEY": generate_job_key(_job(v2=v2, title="Engineer", company="Examplecorp")),
                    "JOB_KEY_V2": v2,
                    "title": "Engineer",
                    "company": "Examplecorp",
                    "location": "Bengaluru",
                    "source": "greenhouse",
                    "link": "https://example.com/111",
                    "ai_score": 5.0,
                    "ai_status": "scored",
                    "reason": "seed",
                    "hiring_manager": "Not Specified",
                    "first_seen": first_seen,
                    "last_seen": first_seen,
                    "times_seen": 2,
                    "currently_active": False,
                    "applied": False,
                    "rejected": False,
                    "interview": False,
                    "offer": False,
                    "notes": "",
                    "posted_at_date": "",
                    "age_days": "",
                }
            ]
        )
        seed.to_csv(self.historical_path, index=False)

        with self._patch_historical_path():
            update_historical_jobs(
                [_job(v2=v2, title="Engineer", company="Examplecorp", score=9.0)]
            )

        result = pd.read_csv(self.historical_path, dtype=str, keep_default_na=False)
        row = result[result["JOB_KEY_V2"] == v2].iloc[0]

        self.assertEqual(str(row["first_seen"]), first_seen)
        self.assertNotEqual(str(row["last_seen"]), first_seen)
        self.assertEqual(str(row["currently_active"]).lower(), "true")
        self.assertEqual(float(row["ai_score"]), 9.0)

    def test_jobs_csv_subset_parity_check(self) -> None:
        jobs = pd.DataFrame(
            {
                "JOB_KEY_V2": ["v2:a:1", "v2:a:2"],
                "ai_status": ["scored", "scored"],
            }
        )
        historical = pd.DataFrame(
            {
                "JOB_KEY_V2": ["v2:a:1"],
                "ai_status": ["scored"],
            }
        )
        out = check_jobs_csv_subset_of_historical(jobs, historical)
        self.assertFalse(out.ok())
        self.assertTrue(any("not in historical" in msg for msg in out.failures))


if __name__ == "__main__":
    unittest.main()
