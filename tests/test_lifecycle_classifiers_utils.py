"""Shared classifier utility tests (T1B)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class ListingClassificationResultTests(unittest.TestCase):
    def test_check_failed_factory(self) -> None:
        from monitor.classifiers.result import ListingClassification

        result = ListingClassification.check_failed("auth:login_wall")
        self.assertEqual(result.listing_status, "check_failed")
        self.assertFalse(result.classification_succeeded)

    def test_succeeded_factory(self) -> None:
        from monitor.classifiers.result import ListingClassification

        result = ListingClassification.succeeded("open", "open:live_shell_apply")
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "open")


class TextHelperTests(unittest.TestCase):
    def test_html_to_text_strips_tags(self) -> None:
        from monitor.classifiers.text import html_to_text

        text = html_to_text("<html><body><h1>Hello</h1><p>World</p></body></html>")
        self.assertEqual(text, "hello world")

    def test_extract_h1_text(self) -> None:
        from monitor.classifiers.text import extract_h1_text

        title = extract_h1_text("<html><body><h1>Senior Engineer</h1></body></html>")
        self.assertEqual(title, "senior engineer")

    def test_extract_document_title_text(self) -> None:
        from monitor.classifiers.text import extract_document_title_text

        title = extract_document_title_text(
            "<html><head><title>Product Manager | fam | LinkedIn</title></head></html>"
        )
        self.assertEqual(title, "product manager | fam | linkedin")


if __name__ == "__main__":
    unittest.main()
