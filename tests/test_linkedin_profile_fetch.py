"""Tests for LinkedIn profile HTML extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach.linkedin_profile_fetch import (  # noqa: E402
    ExperienceEntry,
    ProfileSnapshot,
    _extract_company_from_item_page,
    _extract_first_experience_entry_from_page,
    _extract_title_from_item_page,
    _parse_first_experience_from_html,
    extract_profile_from_page,
    is_linkedin_profile_url,
    normalize_company_name,
    parse_profile_from_html,
    resolve_profile_company,
    resolve_profile_designation,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "linkedin_profile_sample.html"
_HIRING_HEADLINE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_profile_hiring_headline.html"
)
_TARAPRASAD_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_profile_single_role_composite_company.html"
)
_TARAPRASAD_HOME_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_profile_single_role_workplace_home.html"
)
_PROFILE_URL = "https://www.linkedin.com/in/jane-founder"
_VINEESHA_URL = "https://www.linkedin.com/in/vineesha-nandala-779621248"
_TARAPRASAD_URL = "https://www.linkedin.com/in/taraprasad-battha"
_ROLE_TITLE = "Talent Acquisition | Tech & Product Hiring (0 to 1)"
_COMPANY_NAME = "Booking Holdings (NASDAQ: BKNG)"


class LinkedInProfileFetchTests(unittest.TestCase):
    def test_is_linkedin_profile_url(self) -> None:
        self.assertTrue(is_linkedin_profile_url(_PROFILE_URL))
        self.assertFalse(is_linkedin_profile_url("https://www.linkedin.com/posts/x"))

    def test_parse_fixture_extracts_profile_fields(self) -> None:
        html = _FIXTURE.read_text(encoding="utf-8")
        profile = parse_profile_from_html(html, url=_PROFILE_URL)
        self.assertEqual(profile.person_name, "Jane Founder")
        self.assertIn("Founder", profile.headline)
        self.assertEqual(profile.current_role_title, "Founder & CEO")
        self.assertEqual(profile.current_company, "Acme Fintech")
        self.assertEqual(profile.company, "Acme Fintech")
        self.assertEqual(resolve_profile_designation(profile), "Founder & CEO")
        self.assertEqual(resolve_profile_company(profile), "Acme Fintech")

    def test_vineesha_profile_parsed_fields(self) -> None:
        profile = parse_profile_from_html(
            _HIRING_HEADLINE_FIXTURE.read_text(encoding="utf-8"),
            url=_VINEESHA_URL,
        )
        self.assertEqual(profile.headline, "I am hiring")
        self.assertEqual(profile.current_role_title, "Senior Talent Acquisition Specialist")
        self.assertNotEqual(
            profile.current_role_title,
            "Kaerusworld Management Solutions",
        )
        self.assertEqual(resolve_profile_designation(profile), "Senior Talent Acquisition Specialist")

        html = _HIRING_HEADLINE_FIXTURE.read_text(encoding="utf-8")
        entry = _parse_first_experience_from_html(html)
        self.assertEqual(entry.title, "Senior Talent Acquisition Specialist")
        self.assertNotEqual(entry.title, "Kaerusworld Management Solutions")

    def test_parse_hiring_headline_prefers_experience_role_and_company(self) -> None:
        html = _HIRING_HEADLINE_FIXTURE.read_text(encoding="utf-8")
        profile = parse_profile_from_html(html, url=_VINEESHA_URL)
        self.assertEqual(profile.person_name, "Vineesha Nandala")
        self.assertEqual(profile.headline, "I am hiring")
        self.assertEqual(profile.current_role_title, "Senior Talent Acquisition Specialist")
        self.assertNotEqual(
            profile.current_role_title,
            "Kaerusworld Management Solutions",
        )
        self.assertEqual(
            resolve_profile_designation(profile),
            "Senior Talent Acquisition Specialist",
        )

    def test_parse_live_like_experience_anchor_layout(self) -> None:
        entry = _parse_first_experience_from_html(
            _HIRING_HEADLINE_FIXTURE.read_text(encoding="utf-8")
        )
        self.assertEqual(entry.title, "Senior Talent Acquisition Specialist")
        self.assertNotEqual(entry.title, "Kaerusworld Management Solutions")

    def test_resolve_profile_designation_headline_fallback(self) -> None:
        profile = ProfileSnapshot(
            profile_url="https://www.linkedin.com/in/example",
            person_name="Example User",
            headline="Open to work",
            company="Acme",
            fetched_at="2026-06-10T12:00:00+00:00",
        )
        self.assertEqual(resolve_profile_designation(profile), "Open to work")

    def test_resolve_profile_company_prefers_current_company(self) -> None:
        profile = ProfileSnapshot(
            profile_url="https://www.linkedin.com/in/example",
            person_name="Example User",
            headline="Recruiter",
            company="Top Card Co",
            fetched_at="2026-06-10T12:00:00+00:00",
            current_company="Experience Co",
        )
        self.assertEqual(resolve_profile_company(profile), "Experience Co")

    def test_extract_profile_from_page_grouped_experience_uses_nested_role(self) -> None:
        page = MagicMock()
        page.url = _VINEESHA_URL

        def locator_side_effect(selector: str) -> MagicMock:
            locator = MagicMock()
            if selector in {"#experience", "[id='experience']"}:
                locator.count.return_value = 1
                locator.first = locator
                return locator
            if selector == "h1.text-heading-xlarge":
                locator.count.return_value = 1
                locator.inner_text.return_value = "Vineesha Nandala"
                locator.first = locator
                return locator
            if selector == ".text-body-medium.break-words":
                locator.count.return_value = 1
                locator.inner_text.return_value = "I am hiring"
                locator.first = locator
                return locator
            if selector.startswith("#experience ~ div.pvs-list__outer-container ul.pvs-list > li"):
                item = MagicMock()
                company_loc = MagicMock()
                company_loc.count.return_value = 1
                company_loc.nth.return_value = company_loc
                company_loc.inner_text.return_value = "Kaerusworld Management Solutions"
                nested_title_loc = MagicMock()
                nested_title_loc.count.return_value = 1
                nested_title_loc.inner_text.return_value = "Senior Talent Acquisition Specialist"
                nested_title_loc.first = nested_title_loc
                top_title_loc = MagicMock()
                top_title_loc.count.return_value = 1
                top_title_loc.inner_text.return_value = "Kaerusworld Management Solutions"
                top_title_loc.first = top_title_loc

                def item_locator(inner: str) -> MagicMock:
                    if "pvs-entity__sub-components" in inner and "t-bold" in inner:
                        return nested_title_loc
                    if "t-bold" in inner:
                        return top_title_loc
                    return company_loc

                item.count.return_value = 1
                item.first = item
                item.locator.side_effect = item_locator
                locator.count.return_value = 1
                locator.first = item
                return locator
            locator.count.return_value = 0
            locator.first = locator
            return locator

        page.locator.side_effect = locator_side_effect
        page.inner_text.return_value = "Vineesha Nandala I am hiring Experience"

        profile = extract_profile_from_page(page, url=_VINEESHA_URL)
        self.assertEqual(profile.headline, "I am hiring")
        self.assertEqual(profile.current_role_title, "Senior Talent Acquisition Specialist")
        self.assertNotEqual(profile.current_role_title, profile.current_company)
        self.assertEqual(
            resolve_profile_designation(profile),
            "Senior Talent Acquisition Specialist",
        )

    def test_extract_profile_from_page_uses_experience_entry(self) -> None:
        page = MagicMock()
        page.url = _VINEESHA_URL

        def locator_side_effect(selector: str) -> MagicMock:
            locator = MagicMock()
            if selector in {"#experience", "[id='experience']"}:
                locator.count.return_value = 1
                locator.first = locator
                return locator
            if selector == "h1.text-heading-xlarge":
                locator.count.return_value = 1
                locator.inner_text.return_value = "Vineesha Nandala"
                locator.first = locator
                return locator
            if selector == ".text-body-medium.break-words":
                locator.count.return_value = 1
                locator.inner_text.return_value = "I am hiring"
                locator.first = locator
                return locator
            if selector.startswith("#experience ~ div.pvs-list__outer-container ul.pvs-list > li"):
                item = MagicMock()
                title_loc = MagicMock()
                title_loc.count.return_value = 1
                title_loc.inner_text.return_value = "Senior Talent Acquisition Specialist"
                title_loc.first = title_loc
                company_loc = MagicMock()
                company_loc.count.return_value = 1
                company_loc.nth.return_value = company_loc
                company_loc.inner_text.return_value = "Kaerusworld Management Solutions"
                item.count.return_value = 1
                item.first = item
                item.locator.side_effect = lambda inner: (
                    title_loc
                    if "t-bold" in inner
                    else company_loc
                )
                locator.count.return_value = 1
                locator.first = item
                return locator
            locator.count.return_value = 0
            locator.first = locator
            return locator

        page.locator.side_effect = locator_side_effect
        page.inner_text.return_value = "Vineesha Nandala I am hiring Experience"

        profile = extract_profile_from_page(page, url=_VINEESHA_URL)
        self.assertEqual(profile.person_name, "Vineesha Nandala")
        self.assertEqual(profile.headline, "I am hiring")
        self.assertEqual(profile.current_role_title, "Senior Talent Acquisition Specialist")
        self.assertEqual(profile.current_company, "Kaerusworld Management Solutions")
        self.assertEqual(
            resolve_profile_designation(profile),
            "Senior Talent Acquisition Specialist",
        )
        self.assertEqual(
            resolve_profile_company(profile),
            "Kaerusworld Management Solutions",
        )

    def test_extract_first_experience_entry_from_page_skips_date_ranges(self) -> None:
        item = MagicMock()
        title_loc = MagicMock()
        title_loc.count.return_value = 1
        title_loc.inner_text.return_value = "Senior Talent Acquisition Specialist"
        title_loc.first = title_loc
        company_loc = MagicMock()
        company_loc.count.return_value = 2
        company_loc.nth.side_effect = lambda index: company_loc
        company_loc.inner_text.side_effect = [
            "Apr 2026 - Present · 3 mos",
            "Kaerusworld Management Solutions",
            "Kaerusworld Management Solutions",
        ]
        item.locator.side_effect = lambda selector: (
            title_loc if "t-bold" in selector else company_loc
        )

        entry = ExperienceEntry(
            title=_extract_title_from_item_page(item),
            company=_extract_company_from_item_page(item),
        )
        self.assertEqual(entry.title, "Senior Talent Acquisition Specialist")
        self.assertEqual(entry.company, "Kaerusworld Management Solutions")

    def test_normalize_company_name_strips_employment_type_suffix(self) -> None:
        self.assertEqual(
            normalize_company_name("Booking Holdings (NASDAQ: BKNG) · Full-time"),
            _COMPANY_NAME,
        )
        self.assertEqual(normalize_company_name("Acme Corp · Part-time"), "Acme Corp")
        self.assertEqual(normalize_company_name("Acme Fintech"), "Acme Fintech")

    def test_taraprasad_single_role_extracts_role_and_company(self) -> None:
        profile = parse_profile_from_html(
            _TARAPRASAD_FIXTURE.read_text(encoding="utf-8"),
            url=_TARAPRASAD_URL,
        )
        self.assertEqual(profile.current_role_title, _ROLE_TITLE)
        self.assertEqual(profile.current_company, _COMPANY_NAME)
        self.assertEqual(resolve_profile_designation(profile), _ROLE_TITLE)
        self.assertEqual(resolve_profile_company(profile), _COMPANY_NAME)
        self.assertNotIn("Full-time", profile.current_company)

    def test_taraprasad_workplace_home_is_not_designation(self) -> None:
        profile = parse_profile_from_html(
            _TARAPRASAD_HOME_FIXTURE.read_text(encoding="utf-8"),
            url=_TARAPRASAD_URL,
        )
        self.assertEqual(profile.current_role_title, _ROLE_TITLE)
        self.assertNotEqual(profile.current_role_title, "Home")
        self.assertEqual(profile.current_company, _COMPANY_NAME)
        self.assertEqual(resolve_profile_designation(profile), _ROLE_TITLE)

    def test_taraprasad_home_fixture_picks_longest_role_candidate(self) -> None:
        entry = _parse_first_experience_from_html(
            _TARAPRASAD_HOME_FIXTURE.read_text(encoding="utf-8")
        )
        self.assertEqual(entry.title, _ROLE_TITLE)
        self.assertEqual(entry.company, _COMPANY_NAME)


if __name__ == "__main__":
    unittest.main()
