"""Config resolution for LinkedIn priority anchor (qualification landing URL)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from scraper.linkedin_query_orchestrator import (  # noqa: E402
    load_query_catalog,
    resolve_query_url,
)

_EXPECTED_LANDING = (
    "https://www.linkedin.com/jobs/search-results/"
    "?currentJobId=PLACEHOLDER_JOB_001&showHowYouFit=HOW_YOU_FIT"
    "&keywords=Product%20Manager&origin=QUALIFICATION_LANDING"
    "&originToLandingJobPostings=PLACEHOLDER_JOB_001%2CPLACEHOLDER_JOB_002%2CPLACEHOLDER_JOB_003"
    "&geoId=90009633"
)
_STALE_JOB_ID = "PLACEHOLDER_JOB_STALE"


class TopApplicantsAnchorUrlTests(unittest.TestCase):
    def test_json_landing_url(self) -> None:
        cfg_path = _REPO_ROOT / "config" / "linkedin_queries.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        anchor = next(
            q for q in cfg["queries"] if q["id"] == "top_applicants_anchor"
        )
        self.assertEqual(anchor["landing_url"], _EXPECTED_LANDING)
        self.assertNotIn(_STALE_JOB_ID, anchor["landing_url"])

    def test_resolve_query_url_from_catalog(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LINKEDIN_QUALIFICATION_LANDING_URL", None)
            cfg, catalog = load_query_catalog()
            anchor = next(q for q in catalog if q.id == "top_applicants_anchor")
            self.assertEqual(anchor.url, _EXPECTED_LANDING)
            self.assertEqual(
                str(cfg["defaults"]["priority_anchor"]["query_id"]),
                "top_applicants_anchor",
            )

    def test_env_override_takes_precedence(self) -> None:
        override = "https://www.linkedin.com/jobs/search-results/?test=1"
        cfg = json.loads(
            (_REPO_ROOT / "config" / "linkedin_queries.json").read_text(
                encoding="utf-8"
            )
        )
        anchor = next(
            q for q in cfg["queries"] if q["id"] == "top_applicants_anchor"
        )
        with mock.patch.dict(
            os.environ, {"LINKEDIN_QUALIFICATION_LANDING_URL": override}
        ):
            url = resolve_query_url(anchor, cfg["filter_profiles"])
        self.assertEqual(url, override)


if __name__ == "__main__":
    unittest.main()
