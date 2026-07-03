"""Tests for contact email extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach.contact_extract import (  # noqa: E402
    extract_emails_from_text,
    format_application_contact_section,
    merge_application_emails,
)


class ContactExtractTests(unittest.TestCase):
    def test_extract_plain_email(self) -> None:
        emails = extract_emails_from_text(
            "Apply at asavari.kulkarni@company.com with your resume."
        )
        self.assertEqual(emails, ["asavari.kulkarni@company.com"])

    def test_extract_obfuscated_email(self) -> None:
        emails = extract_emails_from_text(
            "Reach us at hiring [at] acme [dot] com for details."
        )
        self.assertIn("hiring@acme.com", emails)

    def test_no_email_returns_empty(self) -> None:
        self.assertEqual(extract_emails_from_text("No contact here."), [])

    def test_merge_application_emails_dedupes(self) -> None:
        merged = merge_application_emails(
            detected_emails=["hr@acme.com"],
            ai_emails=["hr@acme.com", "ops@acme.com"],
        )
        self.assertEqual(merged, ["hr@acme.com", "ops@acme.com"])

    def test_format_application_contact_section(self) -> None:
        section = format_application_contact_section(["hr@acme.com"])
        self.assertEqual(section, "Application Contact:\nhr@acme.com")

    def test_format_application_contact_section_multiple_emails(self) -> None:
        section = format_application_contact_section(["hr@acme.com", "ops@acme.com"])
        self.assertEqual(
            section,
            "Application Contact:\nhr@acme.com\nops@acme.com",
        )


if __name__ == "__main__":
    unittest.main()
