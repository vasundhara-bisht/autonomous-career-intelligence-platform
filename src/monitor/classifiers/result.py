"""Shared classifier result type."""

from __future__ import annotations

from dataclasses import dataclass

from db.listing_status import LISTING_STATUS_CHECK_FAILED


@dataclass(frozen=True)
class ListingClassification:
    """Outcome of a single listing availability classification."""

    listing_status: str
    listing_status_reason: str
    classification_succeeded: bool

    @classmethod
    def check_failed(cls, reason: str) -> ListingClassification:
        return cls(
            listing_status=LISTING_STATUS_CHECK_FAILED,
            listing_status_reason=reason,
            classification_succeeded=False,
        )

    @classmethod
    def succeeded(cls, listing_status: str, reason: str) -> ListingClassification:
        return cls(
            listing_status=listing_status,
            listing_status_reason=reason,
            classification_succeeded=True,
        )
