"""Tests for hiring signal OpenAI extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.hiring_signal_extract import (  # noqa: E402
    apply_profile_enrichment,
    debug_hiring_signal_ingest_enabled,
    extract_hiring_signal_draft,
    format_hiring_signal_notes,
    parse_hiring_signal_draft_payload,
)
from outreach.linkedin_post_fetch import HiringSignalContext, PostSnapshot  # noqa: E402
from outreach.linkedin_profile_fetch import ProfileSnapshot  # noqa: E402

_SNAPSHOT = PostSnapshot(
    url="https://www.linkedin.com/posts/jane-founder_hiring-pm-activity-123",
    body_text="We are hiring a Senior Product Manager at Acme Fintech. Email hr@acme.com",
    author_name="Jane Founder",
    author_profile_url="https://www.linkedin.com/in/jane-founder",
    fetched_at="2026-06-10T12:00:00+00:00",
)
_PROFILE = ProfileSnapshot(
    profile_url="https://www.linkedin.com/in/jane-founder",
    person_name="Jane Founder",
    headline="Founder & CEO at Acme Fintech",
    company="Acme Fintech",
    fetched_at="2026-06-10T12:00:00+00:00",
    current_role_title="Founder & CEO",
    current_company="Acme Fintech",
)
_CONTEXT = HiringSignalContext(
    post=_SNAPSHOT,
    profile=_PROFILE,
    detected_emails=["hr@acme.com"],
)


class HiringSignalExtractTests(unittest.TestCase):
    def test_parse_payload_maps_fields(self) -> None:
        draft = parse_hiring_signal_draft_payload(
            {
                "hiring_signal_type": "founder_post",
                "person_name": "Jane Founder",
                "company": "Acme Fintech",
                "designation": "Founder",
                "hiring_signal_notes": [
                    "Founder hiring for core product team.",
                    "Role: Senior Product Manager.",
                ],
            },
            context=_CONTEXT,
        )
        prefill = draft.to_prefill_dict()
        self.assertEqual(prefill["hiring_signal_type"], "founder_post")
        self.assertEqual(prefill["company"], "Acme Fintech")
        self.assertIn("- Founder hiring for core product team.", prefill["notes"])
        self.assertIn("- Role: Senior Product Manager.", prefill["notes"])
        self.assertEqual(prefill["hiring_signal_url"], _SNAPSHOT.url)

    def test_format_hiring_signal_notes_application_sections(self) -> None:
        notes = format_hiring_signal_notes(
            {
                "hiring_signal_notes": ["Hiring PM role."],
                "application_emails": ["asavari.kulkarni@company.com"],
                "application_instructions": "Send LinkedIn profile and short note to HR.",
            },
            detected_emails=["hr@acme.com"],
        )
        self.assertIn("- Hiring PM role.", notes)
        self.assertIn("Application Contact:", notes)
        self.assertIn("hr@acme.com", notes)
        self.assertIn("asavari.kulkarni@company.com", notes)
        self.assertNotIn("mailto:", notes)
        self.assertIn("Application Instructions:", notes)
        self.assertIn("Send LinkedIn profile", notes)

    def test_format_hiring_signal_notes_legacy_summary(self) -> None:
        notes = format_hiring_signal_notes({"hiring_summary": "Hiring Senior PM."})
        self.assertEqual(notes, "Hiring Senior PM.")

    def test_apply_profile_enrichment_fills_empty_fields(self) -> None:
        from agent.hiring_signal_extract import HiringSignalDraft

        draft = HiringSignalDraft(
            hiring_signal_type="founder_post",
            person_name="",
            company="",
            designation="",
            notes="",
            linkedin_url="",
            hiring_signal_url=_SNAPSHOT.url,
            outreach_channel="linkedin",
        )
        enriched = apply_profile_enrichment(draft, profile=_PROFILE, post=_SNAPSHOT)
        self.assertEqual(enriched.person_name, "Jane Founder")
        self.assertEqual(enriched.designation, "Founder & CEO")
        self.assertEqual(enriched.company, "Acme Fintech")

    def test_apply_profile_enrichment_overrides_post_role_designation(self) -> None:
        from agent.hiring_signal_extract import HiringSignalDraft

        draft = HiringSignalDraft(
            hiring_signal_type="linkedin_hiring_post",
            person_name="Vineesha Nandala",
            company="Kaerusworld Management Solutions",
            designation="Product Manager - UPI",
            notes="- Position: Product Manager - UPI\n- Location: Bangalore",
            linkedin_url="https://www.linkedin.com/in/vineesha-nandala-779621248",
            hiring_signal_url="https://www.linkedin.com/posts/vineesha-nandala_hiring",
            outreach_channel="linkedin",
        )
        profile = ProfileSnapshot(
            profile_url="https://www.linkedin.com/in/vineesha-nandala-779621248",
            person_name="Vineesha Nandala",
            headline="I am hiring",
            company="",
            fetched_at="2026-06-10T12:00:00+00:00",
            current_role_title="Senior Talent Acquisition Specialist",
            current_company="Kaerusworld Management Solutions",
        )
        post = PostSnapshot(
            url=draft.hiring_signal_url,
            body_text="Position: Product Manager - UPI. Bangalore.",
            author_name="Vineesha Nandala",
            author_profile_url=profile.profile_url,
            fetched_at="2026-06-10T12:00:00+00:00",
        )
        enriched = apply_profile_enrichment(draft, profile=profile, post=post)
        self.assertEqual(enriched.designation, "Senior Talent Acquisition Specialist")
        self.assertEqual(enriched.company, "Kaerusworld Management Solutions")
        self.assertIn("Product Manager - UPI", enriched.notes)

    def test_apply_profile_enrichment_headline_fallback_without_role(self) -> None:
        from agent.hiring_signal_extract import HiringSignalDraft

        draft = HiringSignalDraft(
            hiring_signal_type="linkedin_hiring_post",
            person_name="Example User",
            company="Acme",
            designation="Product Manager",
            notes="",
            linkedin_url="https://www.linkedin.com/in/example",
            hiring_signal_url=_SNAPSHOT.url,
            outreach_channel="linkedin",
        )
        profile = ProfileSnapshot(
            profile_url="https://www.linkedin.com/in/example",
            person_name="Example User",
            headline="Recruiting Lead",
            company="Acme",
            fetched_at="2026-06-10T12:00:00+00:00",
        )
        enriched = apply_profile_enrichment(draft, profile=profile, post=_SNAPSHOT)
        self.assertEqual(enriched.designation, "Recruiting Lead")

    def test_extract_uses_openai_response(self) -> None:
        mock_response = MagicMock()
        mock_response.output_text = """
        {
          "hiring_signal_type": "linkedin_hiring_post",
          "person_name": "Recruiter Pat",
          "company": "Acme",
          "designation": "Recruiter",
          "hiring_signal_notes": ["Hiring PM role."]
        }
        """
        with patch("agent.hiring_signal_extract.client") as mock_client:
            mock_client.responses.create.return_value = mock_response
            draft, ai_ok = extract_hiring_signal_draft(_CONTEXT)
        self.assertTrue(ai_ok)
        self.assertEqual(draft.hiring_signal_type, "linkedin_hiring_post")
        self.assertEqual(draft.person_name, "Jane Founder")
        self.assertEqual(draft.designation, "Founder & CEO")
        self.assertEqual(draft.company, "Acme Fintech")

    def test_apply_profile_enrichment_logs_profile_fields_when_debug_enabled(self) -> None:
        from agent.hiring_signal_extract import HiringSignalDraft

        draft = HiringSignalDraft(
            hiring_signal_type="linkedin_hiring_post",
            person_name="",
            company="",
            designation="",
            notes="",
            linkedin_url="",
            hiring_signal_url=_SNAPSHOT.url,
            outreach_channel="linkedin",
        )
        with patch.dict("os.environ", {"DEBUG_HIRING_SIGNAL_INGEST": "1"}):
            self.assertTrue(debug_hiring_signal_ingest_enabled())
            with patch("agent.hiring_signal_extract._ingest_debug") as mock_debug:
                apply_profile_enrichment(draft, profile=_PROFILE, post=_SNAPSHOT)
        mock_debug.assert_called()
        message = mock_debug.call_args[0][0]
        self.assertIn("current_role_title='Founder & CEO'", message)
        self.assertIn("current_company='Acme Fintech'", message)

    def test_extract_falls_back_on_invalid_json(self) -> None:
        mock_response = MagicMock()
        mock_response.output_text = "not-json"
        with patch("agent.hiring_signal_extract.client") as mock_client:
            mock_client.responses.create.return_value = mock_response
            draft, ai_ok = extract_hiring_signal_draft(_CONTEXT)
        self.assertFalse(ai_ok)
        self.assertEqual(draft.person_name, "Jane Founder")
        self.assertIn("AI extraction failed", draft.notes)
        self.assertIn("Application Contact:", draft.notes)

    def test_extract_falls_back_when_client_missing(self) -> None:
        with patch("agent.hiring_signal_extract.client", None):
            draft, ai_ok = extract_hiring_signal_draft(_CONTEXT)
        self.assertFalse(ai_ok)
        self.assertEqual(draft.linkedin_url, _PROFILE.profile_url)


if __name__ == "__main__":
    unittest.main()
