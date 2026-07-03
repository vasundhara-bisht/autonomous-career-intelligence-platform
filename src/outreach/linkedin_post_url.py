"""LinkedIn post URL validation and normalization for hiring signal ingestion."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

_LINKEDIN_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})
_POST_PATH_PATTERNS = (
    re.compile(r"^/posts/[^/]+", re.IGNORECASE),
    re.compile(r"^/feed/update/urn:li:(activity|share|ugcPost):", re.IGNORECASE),
    re.compile(r"^/feed/update/[^/]+", re.IGNORECASE),
)


class LinkedInPostUrlError(ValueError):
    """Raised when a URL is not a supported LinkedIn post pattern."""


def _normalize_host(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{url.strip()}")
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_linkedin_post_url(url: str) -> bool:
    """Return True when ``url`` matches a supported LinkedIn post pattern."""
    try:
        validate_linkedin_post_url(url)
        return True
    except LinkedInPostUrlError:
        return False


def validate_linkedin_post_url(url: str) -> str:
    """
    Validate and return a canonical LinkedIn post URL.

    Supported patterns:
    - /posts/{slug}
    - /feed/update/urn:li:activity:...
    - /feed/update/urn:li:share:...
    """
    text = str(url or "").strip()
    if not text:
        raise LinkedInPostUrlError("Hiring Signal URL is required for LinkedIn fetch.")

    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = _normalize_host(text)
    if host not in _LINKEDIN_HOSTS:
        raise LinkedInPostUrlError("Ingestion supports LinkedIn posts only.")

    path = parsed.path or ""
    if not any(pattern.match(path) for pattern in _POST_PATH_PATTERNS):
        raise LinkedInPostUrlError("Ingestion supports LinkedIn posts only.")

    normalized = urlunparse(
        (
            "https",
            "www.linkedin.com",
            path.rstrip("/") if path.endswith("/") and path != "/" else path,
            "",
            parsed.query,
            "",
        )
    )
    return normalized
