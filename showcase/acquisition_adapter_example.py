"""Acquisition adapter pattern — illustrative excerpt, not a production scraper.

The private repository's `scraper/` package contains several thousand lines
of adapters for LinkedIn, Instahyre, Greenhouse, Lever, and Himalayas,
including anti-bot handling, pagination, and provider-specific quirks. None
of that ships here.

This file demonstrates the *shape* of the pattern used across those
adapters — fetch, normalize, yield a common record — against a small bundled
fixture instead of a live endpoint, so it runs safely and deterministically
with no network access and no real company/query data.

Run:

    python showcase/acquisition_adapter_example.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

# Bundled fixture standing in for a real provider response. The production
# adapters call each provider's API/HTML and handle retries, pagination, and
# per-provider field quirks; that logic is not reproduced here.
_FIXTURE_RESPONSE = [
    {
        "id": "sample-001",
        "title": "  Senior Product Manager ",
        "company_name": "Example Robotics Co",
        "location": "Remote",
        "url": "https://example.com/careers/sample-001",
        "posted": "3 days ago",
    },
    {
        "id": "sample-002",
        "title": "Product Manager, Platform",
        "company_name": " Example Robotics Co ",
        "location": "Bengaluru, India",
        "url": "https://example.com/careers/sample-002",
        "posted": "1 week ago",
    },
]


@dataclass(frozen=True)
class JobRecord:
    """Common normalized shape a downstream pipeline would consume."""

    source_id: str
    title: str
    company: str
    location: str
    url: str
    raw_posted_label: str


def normalize_record(raw: dict) -> JobRecord:
    """Trim/normalize a single provider record into the common shape."""
    return JobRecord(
        source_id=str(raw["id"]).strip(),
        title=str(raw["title"]).strip(),
        company=str(raw["company_name"]).strip(),
        location=str(raw.get("location", "")).strip() or "Unspecified",
        url=str(raw["url"]).strip(),
        raw_posted_label=str(raw.get("posted", "")).strip(),
    )


def fetch_sample_jobs() -> Iterator[JobRecord]:
    """Stand-in for a real `fetch()` call — yields normalized records from the fixture."""
    for raw in _FIXTURE_RESPONSE:
        yield normalize_record(raw)


if __name__ == "__main__":
    for job in fetch_sample_jobs():
        print(f"{job.title} @ {job.company} ({job.location}) -> {job.url}")
