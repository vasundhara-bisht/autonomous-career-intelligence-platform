"""Canonical Outreach Intelligence status and channel values (dashboard-only)."""

from __future__ import annotations

import pandas as pd

OUTREACH_STATUSES: tuple[str, ...] = (
    "planned",
    "sent",
    "replied",
    "meeting_scheduled",
    "referral_offered",
    "no_response",
    "closed",
)
OUTREACH_CHANNELS: tuple[str, ...] = ("linkedin", "email", "phone", "other")
ACTIVE_OUTREACH_STATUSES: tuple[str, ...] = (
    "sent",
    "replied",
    "meeting_scheduled",
    "referral_offered",
)
TERMINAL_FOLLOWUP_STATUSES: tuple[str, ...] = ("closed", "no_response")

OUTREACH_STATUS_OPTIONS: list[str] = list(OUTREACH_STATUSES)
OUTREACH_CHANNEL_OPTIONS: list[str] = list(OUTREACH_CHANNELS)

_STATUS_LABELS: dict[str, str] = {
    "planned": "Planned",
    "sent": "Sent",
    "replied": "Replied",
    "meeting_scheduled": "Meeting Scheduled",
    "referral_offered": "Referral Offered",
    "no_response": "No Response",
    "closed": "Closed",
}

OUTREACH_STATUS_LABEL_OPTIONS: list[str] = [
    _STATUS_LABELS[s] for s in OUTREACH_STATUSES
]

_CHANNEL_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn",
    "email": "Email",
    "phone": "Phone",
    "other": "Other",
}


def normalize_outreach_status(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "planned"
    text = str(value).strip().lower().replace(" ", "_")
    if text in {"", "nan", "none"}:
        return "planned"
    if text in OUTREACH_STATUSES:
        return text
    for stored, label in _STATUS_LABELS.items():
        if text == label.lower().replace(" ", "_"):
            return stored
    return "planned"


def outreach_status_label(status: str) -> str:
    normalized = normalize_outreach_status(status)
    return _STATUS_LABELS.get(normalized, normalized.replace("_", " ").title())


def normalize_outreach_channel(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "linkedin"
    text = str(value).strip().lower()
    if text in {"", "nan", "none"}:
        return "linkedin"
    if text in OUTREACH_CHANNELS:
        return text
    for stored, label in _CHANNEL_LABELS.items():
        if text == label.lower():
            return stored
    return "other"


def outreach_channel_label(channel: str) -> str:
    normalized = normalize_outreach_channel(channel)
    return _CHANNEL_LABELS.get(normalized, normalized.replace("_", " ").title())


HIRING_SIGNAL_TYPES: tuple[str, ...] = (
    "linkedin_hiring_post",
    "founder_post",
    "recruiter_message",
    "whatsapp_referral",
    "personal_referral",
    "mentor_referral",
    "direct_outreach",
    "other",
    "job_listing",
)
HIRING_SIGNAL_NOT_SET = "__not_set__"

HIRING_SIGNAL_OPTIONS: list[str] = list(HIRING_SIGNAL_TYPES)
HIRING_SIGNAL_FILTER_OPTIONS: list[str] = list(HIRING_SIGNAL_TYPES) + [HIRING_SIGNAL_NOT_SET]

_SIGNAL_LABELS: dict[str, str] = {
    "linkedin_hiring_post": "LinkedIn Hiring Post",
    "founder_post": "Founder Post",
    "recruiter_message": "Recruiter Message",
    "whatsapp_referral": "WhatsApp Referral",
    "personal_referral": "Personal Referral",
    "mentor_referral": "Mentor Referral",
    "direct_outreach": "Direct Outreach",
    "other": "Other",
    "job_listing": "Job Listing",
}

HIRING_SIGNAL_LABEL_OPTIONS: list[str] = [
    _SIGNAL_LABELS[s] for s in HIRING_SIGNAL_TYPES
]


def normalize_hiring_signal_type(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower().replace(" ", "_")
    if text in {"", "nan", "none", "not_set"}:
        return ""
    if text in HIRING_SIGNAL_TYPES:
        return text
    for stored, label in _SIGNAL_LABELS.items():
        if text == label.lower().replace(" ", "_"):
            return stored
    return "other"


def hiring_signal_label(signal_type: str) -> str:
    normalized = normalize_hiring_signal_type(signal_type)
    if not normalized:
        return "Not set"
    return _SIGNAL_LABELS.get(normalized, normalized.replace("_", " ").title())


def hiring_signal_filter_label(option: str) -> str:
    if option == HIRING_SIGNAL_NOT_SET:
        return "Not set"
    return hiring_signal_label(option)
