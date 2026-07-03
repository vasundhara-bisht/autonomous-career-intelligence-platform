"""Unit tests for src/agent/job_outreach_prefill.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT / "src"),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.job_outreach_prefill import (  # noqa: E402
    _resolve_company,
    _resolve_designation,
    _resolve_person_name,
    run_job_outreach_prefill,
)
from db.read.job_outreach import JobOutreachContext  # noqa: E402


def _make_ctx(**kwargs) -> JobOutreachContext:
    defaults = dict(
        job_key_v2="jkv2_test",
        title="Senior PM",
        company="Acme Corp",
        location="Bangalore",
        posted_at_date="2026-06-10",
        link="https://acme.jobs/sr-pm",
        description="We need a PM with 5+ years of experience.",
        recruiter_name="Priya Sharma",
        recruiter_title="Senior Recruiter",
        recruiter_company="Acme Corp",
        hiring_manager="Jane Doe",
    )
    defaults.update(kwargs)
    return JobOutreachContext(**defaults)


class ResolveFieldsTests(unittest.TestCase):

    def test_person_name_prefers_recruiter(self) -> None:
        ctx = _make_ctx(recruiter_name="Priya", hiring_manager="Jane")
        self.assertEqual(_resolve_person_name(ctx), "Priya")

    def test_person_name_falls_back_to_hiring_manager(self) -> None:
        ctx = _make_ctx(recruiter_name="", hiring_manager="Jane")
        self.assertEqual(_resolve_person_name(ctx), "Jane")

    def test_person_name_blank_when_both_absent(self) -> None:
        ctx = _make_ctx(recruiter_name="", hiring_manager="")
        self.assertEqual(_resolve_person_name(ctx), "")

    def test_designation_from_recruiter_title(self) -> None:
        ctx = _make_ctx(recruiter_title="Head of TA")
        self.assertEqual(_resolve_designation(ctx), "Head of TA")

    def test_designation_blank_when_no_recruiter_title(self) -> None:
        ctx = _make_ctx(recruiter_title="")
        self.assertEqual(_resolve_designation(ctx), "")

    def test_company_prefers_recruiter_company(self) -> None:
        ctx = _make_ctx(recruiter_company="TalentCo", company="Acme")
        self.assertEqual(_resolve_company(ctx), "TalentCo")

    def test_company_falls_back_to_job_company(self) -> None:
        ctx = _make_ctx(recruiter_company="", company="Acme")
        self.assertEqual(_resolve_company(ctx), "Acme")


class RunJobOutreachPrefillTests(unittest.TestCase):

    def _make_ai_ok(self, msg: str = "Hi Priya, saw Acme is hiring."):
        mock_fn = MagicMock(return_value=(msg, True))
        return mock_fn

    def test_returns_empty_dict_when_job_not_found(self) -> None:
        mock_ctx = MagicMock(return_value=None)
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", mock_ctx):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, warning = run_job_outreach_prefill("missing_key")

        self.assertEqual(draft, {})
        self.assertIn("not found", warning)

    def test_returns_empty_dict_on_db_error(self) -> None:
        with patch("agent.job_outreach_prefill.get_session", side_effect=RuntimeError("DB down")):
            draft, warning = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft, {})
        self.assertIn("Database error", warning)

    def test_draft_has_correct_outreach_type_and_signal_type(self) -> None:
        ctx = _make_ctx()
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, _ = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft["outreach_type"], "job_outreach")
        self.assertEqual(draft["hiring_signal_type"], "job_listing")

    def test_notes_always_empty_in_draft(self) -> None:
        ctx = _make_ctx(description="Long job description text here.")
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, _ = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft.get("notes", ""), "")

    def test_description_passed_to_ai_not_draft(self) -> None:
        """Job description goes to AI as context, never into draft['notes']."""
        ctx = _make_ctx(description="PM role at Acme for 5+ years.")
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, _ = run_job_outreach_prefill("jkv2_test")

        call_kwargs = mock_fn.call_args.kwargs
        self.assertEqual(call_kwargs["notes"], "PM role at Acme for 5+ years.")
        self.assertEqual(draft.get("notes", ""), "")

    def test_opportunity_id_and_url_in_draft(self) -> None:
        ctx = _make_ctx(job_key_v2="jkv2_test", link="https://acme.jobs/sr-pm")
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, _ = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft["opportunity_id"], "jkv2_test")
        self.assertEqual(draft["opportunity_url"], "https://acme.jobs/sr-pm")

    def test_ai_message_stored_in_draft(self) -> None:
        ctx = _make_ctx()
        mock_fn = self._make_ai_ok("Hi Priya, loved what Acme is building.")
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, _ = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft["outreach_message"], "Hi Priya, loved what Acme is building.")

    def test_empty_description_warning(self) -> None:
        ctx = _make_ctx(description="")
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            _, warning = run_job_outreach_prefill("jkv2_test")

        self.assertIn("No job description", warning)

    def test_no_recruiter_no_hiring_manager_warning(self) -> None:
        ctx = _make_ctx(recruiter_name="", hiring_manager="")
        mock_fn = self._make_ai_ok()
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            _, warning = run_job_outreach_prefill("jkv2_test")

        self.assertIn("No recruiter", warning)

    def test_ai_failure_warning_and_blank_message(self) -> None:
        ctx = _make_ctx()
        mock_fn = MagicMock(return_value=("", False))
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            draft, warning = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(draft["outreach_message"], "")
        self.assertIn("AI message generation failed", warning)

    def test_no_warning_on_full_success(self) -> None:
        ctx = _make_ctx()
        mock_fn = self._make_ai_ok("Hi Priya!")
        with patch("agent.job_outreach_prefill.get_session") as mock_sess, \
             patch("agent.job_outreach_prefill.load_job_outreach_context", return_value=ctx), \
             patch("agent.job_outreach_prefill.generate_outreach_message", mock_fn):
            mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_sess.return_value.__exit__ = MagicMock(return_value=False)
            _, warning = run_job_outreach_prefill("jkv2_test")

        self.assertEqual(warning, "")


if __name__ == "__main__":
    unittest.main()
