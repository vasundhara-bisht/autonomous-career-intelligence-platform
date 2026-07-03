"""Merge job-linked prefill and LinkedIn ingest draft for Add Outreach form."""

from __future__ import annotations

_PREFILL_FIELDS = (
    "person_name",
    "company",
    "designation",
    "linkedin_url",
    "hiring_signal_type",
    "hiring_signal_url",
    "notes",
    "outreach_channel",
    "outreach_message",
)


def merge_outreach_form_defaults(
    *,
    job_prefill: dict[str, str] | None,
    ingest_draft: dict[str, str] | None,
) -> dict[str, str]:
    """
    Merge job-linked prefill with URL ingest draft.

    Precedence:
    - Job prefill provides base values (including opportunity_id/url — not in form fields).
    - Ingest draft overwrites empty scalar form fields only.
    - Job link fields from job_prefill are never cleared by ingest draft.
    """
    merged: dict[str, str] = dict(job_prefill or {})
    draft = dict(ingest_draft or {})

    for field in _PREFILL_FIELDS:
        draft_value = str(draft.get(field, "") or "").strip()
        if not draft_value:
            continue
        current = str(merged.get(field, "") or "").strip()
        if not current:
            merged[field] = draft_value

    return merged
