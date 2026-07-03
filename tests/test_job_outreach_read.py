"""Unit tests for src/db/read/job_outreach.py."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT / "src"),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.read.job_outreach import JobOutreachContext, load_job_outreach_context  # noqa: E402


def _make_job(
    *,
    id: int = 1,
    job_key_v2: str = "jkv2_abc",
    title: str = "Senior PM",
    company: str = "Acme Corp",
    location: str = "Bangalore",
    posted_at_date: str = "2026-06-10",
    link: str = "https://acme.jobs/sr-pm",
    hiring_manager: str = "Jane Doe",
) -> MagicMock:
    j = MagicMock()
    j.id = id
    j.job_key_v2 = job_key_v2
    j.title = title
    j.company = company
    j.location = location
    j.posted_at_date = posted_at_date
    j.link = link
    j.hiring_manager = hiring_manager
    return j


def _make_description(description: str = "We are hiring a PM…") -> MagicMock:
    d = MagicMock()
    d.description = description
    return d


def _make_recruiter(
    *,
    id: int = 10,
    name: str = "Priya Sharma",
    title: str = "Senior Recruiter",
    company: str = "Acme Corp",
) -> MagicMock:
    r = MagicMock()
    r.id = id
    r.recruiter_name = name
    r.recruiter_title = title
    r.recruiter_company = company
    return r


def _make_link(recruiter_id: int = 10, job_id: int = 1) -> MagicMock:
    lnk = MagicMock()
    lnk.recruiter_id = recruiter_id
    lnk.job_id = job_id
    return lnk


def _scalar_sequence(*values):
    """Return a mock session.execute() chain for multiple scalar_one_or_none calls."""
    results = iter(values)

    def _scalar_one_or_none():
        return next(results, None)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.side_effect = _scalar_one_or_none
    return exec_result


class LoadJobOutreachContextTests(unittest.TestCase):

    def _make_session(self, job, desc, link, recruiter):
        """Build a mock Session whose execute() returns objects in call order."""
        session = MagicMock()
        calls = iter([job, desc, link, recruiter])

        def _execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = next(calls, None)
            return result

        session.execute.side_effect = _execute
        return session

    def test_returns_none_when_job_missing(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        ctx = load_job_outreach_context(session, "missing_key")
        self.assertIsNone(ctx)

    def test_full_context_with_recruiter(self) -> None:
        job = _make_job()
        desc = _make_description("We are looking for a PM with 5+ years.")
        link = _make_link()
        recruiter = _make_recruiter()

        session = self._make_session(job, desc, link, recruiter)
        ctx = load_job_outreach_context(session, "jkv2_abc")

        self.assertIsInstance(ctx, JobOutreachContext)
        self.assertEqual(ctx.job_key_v2, "jkv2_abc")
        self.assertEqual(ctx.title, "Senior PM")
        self.assertEqual(ctx.company, "Acme Corp")
        self.assertEqual(ctx.location, "Bangalore")
        self.assertEqual(ctx.posted_at_date, "2026-06-10")
        self.assertEqual(ctx.link, "https://acme.jobs/sr-pm")
        self.assertEqual(ctx.description, "We are looking for a PM with 5+ years.")
        self.assertEqual(ctx.recruiter_name, "Priya Sharma")
        self.assertEqual(ctx.recruiter_title, "Senior Recruiter")
        self.assertEqual(ctx.recruiter_company, "Acme Corp")
        self.assertEqual(ctx.hiring_manager, "Jane Doe")

    def test_no_description_returns_empty_string(self) -> None:
        job = _make_job()
        session = self._make_session(job, None, None, None)
        ctx = load_job_outreach_context(session, "jkv2_abc")

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.description, "")

    def test_no_recruiter_link_returns_empty_recruiter_fields(self) -> None:
        job = _make_job()
        desc = _make_description("Some description.")
        session = self._make_session(job, desc, None, None)
        ctx = load_job_outreach_context(session, "jkv2_abc")

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.recruiter_name, "")
        self.assertEqual(ctx.recruiter_title, "")
        self.assertEqual(ctx.recruiter_company, "")

    def test_no_recruiter_row_returns_empty_recruiter_fields(self) -> None:
        job = _make_job()
        desc = _make_description()
        link = _make_link()
        session = self._make_session(job, desc, link, None)
        ctx = load_job_outreach_context(session, "jkv2_abc")

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.recruiter_name, "")

    def test_none_fields_coerced_to_empty_string(self) -> None:
        job = _make_job(location=None, posted_at_date=None, link=None, hiring_manager=None)
        session = self._make_session(job, None, None, None)
        ctx = load_job_outreach_context(session, "jkv2_abc")

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.location, "")
        self.assertEqual(ctx.posted_at_date, "")
        self.assertEqual(ctx.link, "")
        self.assertEqual(ctx.hiring_manager, "")


if __name__ == "__main__":
    unittest.main()
