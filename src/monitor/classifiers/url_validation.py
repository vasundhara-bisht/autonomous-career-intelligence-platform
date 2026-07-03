"""Pre-navigation URL validation for Scheduler B classifiers."""

from __future__ import annotations

import re

from agent.job_identity import extract_instahyre_job_id, extract_linkedin_job_id

from monitor.classifiers.result import ListingClassification

_INSTAHYRE_HOST_RE = re.compile(r"instahyre\.com", re.IGNORECASE)
_LINKEDIN_HOST_RE = re.compile(r"linkedin\.com", re.IGNORECASE)
_INSTAHYRE_STABLE_JOB_PATH_RE = re.compile(r"/job-(\d+)(?:/|$|-)", re.IGNORECASE)


def validate_linkedin_job_url(url: str | None) -> ListingClassification | None:
    """
    Return check_failed when the stored URL cannot be monitored.

    Returns None when the URL is well-formed enough to navigate.
    """
    raw = (url or "").strip()
    if not raw:
        return ListingClassification.check_failed("invalid_url:empty")

    if not _LINKEDIN_HOST_RE.search(raw):
        return ListingClassification.check_failed("invalid_url:not_linkedin_host")

    job_id = extract_linkedin_job_id(raw)
    if not job_id:
        return ListingClassification.check_failed("invalid_url:missing_job_id")

    return None


def validate_instahyre_job_url(url: str | None) -> ListingClassification | None:
    """
    Return check_failed when the stored URL cannot be monitored.

    Returns None when the URL is well-formed enough to navigate.
    """
    raw = (url or "").strip()
    if not raw:
        return ListingClassification.check_failed("invalid_url:empty")

    if not _INSTAHYRE_HOST_RE.search(raw):
        return ListingClassification.check_failed("invalid_url:not_instahyre_host")

    job_id = extract_instahyre_job_id(raw)
    if not job_id:
        return ListingClassification.check_failed("invalid_url:missing_job_id")

    if not _INSTAHYRE_STABLE_JOB_PATH_RE.search(raw):
        return ListingClassification.check_failed("invalid_url:not_stable_job_path")

    return None
