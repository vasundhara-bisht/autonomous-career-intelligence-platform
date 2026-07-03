"""OpenAI-assisted hiring signal draft extraction for Outreach Intelligence."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
import traceback
from typing import Any

from openai import OpenAI

from agent.ai_runtime_config import resolve_openai_model
from outreach.contact_extract import (
    format_application_contact_section,
    merge_application_emails,
)
from outreach.linkedin_post_fetch import HiringSignalContext, PostSnapshot
from outreach.linkedin_profile_fetch import ProfileSnapshot, resolve_profile_company, resolve_profile_designation

_INGEST_SIGNAL_TYPES = ("linkedin_hiring_post", "founder_post")

api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    api_key = api_key.strip()
client = OpenAI(api_key=api_key) if api_key else None


@dataclass(frozen=True)
class HiringSignalDraft:
    hiring_signal_type: str
    person_name: str
    company: str
    designation: str
    notes: str
    linkedin_url: str
    hiring_signal_url: str
    outreach_channel: str

    def to_prefill_dict(self) -> dict[str, str]:
        return {
            "hiring_signal_type": self.hiring_signal_type,
            "person_name": self.person_name,
            "company": self.company,
            "designation": self.designation,
            "notes": self.notes,
            "linkedin_url": self.linkedin_url,
            "hiring_signal_url": self.hiring_signal_url,
            "outreach_channel": self.outreach_channel,
        }


def debug_hiring_signal_ingest_enabled() -> bool:
    return os.environ.get("DEBUG_HIRING_SIGNAL_INGEST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _ingest_debug(message: str) -> None:
    if debug_hiring_signal_ingest_enabled():
        print(message)


def _strip_json_markdown(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 1)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip().replace("\u201c", '"').replace("\u201d", '"')


def _normalize_optional_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "null", "none", "nan"}:
        return ""
    return text


def _normalize_signal_type(value: object) -> str:
    text = _normalize_optional_text(value).lower().replace(" ", "_")
    if text in _INGEST_SIGNAL_TYPES:
        return text
    return ""


def _normalize_email_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        email
        for item in value
        if (email := _normalize_optional_text(item).lower())
    ]


def format_hiring_signal_notes(
    payload: dict[str, Any],
    *,
    detected_emails: list[str] | None = None,
) -> str:
    """Build Hiring Signal Notes from bullets, application contact, and instructions."""
    sections: list[str] = []

    bullets = payload.get("hiring_signal_notes")
    if isinstance(bullets, list):
        bullet_lines: list[str] = []
        for item in bullets:
            text = _normalize_optional_text(item)
            if text:
                bullet_lines.append(f"- {text}")
        if bullet_lines:
            sections.append("\n".join(bullet_lines[:8]))
    elif payload.get("hiring_summary") or payload.get("notes"):
        summary = _normalize_optional_text(
            payload.get("hiring_summary") or payload.get("notes")
        )
        if summary:
            sections.append(summary)

    emails = merge_application_emails(
        detected_emails=list(detected_emails or []),
        ai_emails=_normalize_email_list(payload.get("application_emails")),
    )
    contact_section = format_application_contact_section(emails)
    if contact_section:
        sections.append(contact_section)

    instructions = _normalize_optional_text(payload.get("application_instructions"))
    if instructions:
        sections.append(f"Application Instructions:\n{instructions}")

    return "\n\n".join(section for section in sections if section)


def apply_profile_enrichment(
    draft: HiringSignalDraft,
    *,
    profile: ProfileSnapshot | None,
    post: PostSnapshot,
) -> HiringSignalDraft:
    """Prefer profile identity fields when profile enrichment succeeded."""
    if profile is None:
        return draft

    person_name = profile.person_name or draft.person_name or post.author_name
    designation = resolve_profile_designation(profile) or draft.designation
    company = resolve_profile_company(profile) or draft.company
    linkedin_url = profile.profile_url or draft.linkedin_url or post.author_profile_url

    _ingest_debug(
        "apply_profile_enrichment: "
        f"person_name={person_name!r} "
        f"designation={designation!r} "
        f"company={company!r} "
        f"profile.current_role_title={profile.current_role_title!r} "
        f"profile.current_company={profile.current_company!r} "
        f"profile.headline={profile.headline!r} "
        f"profile.company={profile.company!r}"
    )

    return replace(
        draft,
        person_name=person_name,
        designation=designation,
        company=company,
        linkedin_url=linkedin_url,
    )


def _fallback_draft(
    context: HiringSignalContext,
    *,
    reason: str,
) -> HiringSignalDraft:
    snapshot = context.post
    notes_parts = [reason]
    if snapshot.author_name:
        notes_parts.append(f"Author: {snapshot.author_name}")
    if snapshot.body_text:
        notes_parts.append(snapshot.body_text[:500])

    contact_section = format_application_contact_section(context.detected_emails)
    notes_body = " | ".join(part for part in notes_parts if part)
    if contact_section:
        notes_body = f"{notes_body}\n\n{contact_section}" if notes_body else contact_section

    draft = HiringSignalDraft(
        hiring_signal_type="",
        person_name=snapshot.author_name,
        company="",
        designation="",
        notes=notes_body,
        linkedin_url=snapshot.author_profile_url,
        hiring_signal_url=snapshot.url,
        outreach_channel="linkedin",
    )
    return apply_profile_enrichment(draft, profile=context.profile, post=snapshot)


def parse_hiring_signal_draft_payload(
    payload: dict[str, Any],
    *,
    context: HiringSignalContext,
) -> HiringSignalDraft:
    snapshot = context.post
    signal_type = _normalize_signal_type(payload.get("hiring_signal_type"))
    person_name = _normalize_optional_text(payload.get("person_name"))
    if not person_name:
        person_name = snapshot.author_name
    linkedin_url = snapshot.author_profile_url
    draft = HiringSignalDraft(
        hiring_signal_type=signal_type,
        person_name=person_name,
        company=_normalize_optional_text(payload.get("company")),
        designation=_normalize_optional_text(payload.get("designation")),
        notes=format_hiring_signal_notes(
            payload,
            detected_emails=context.detected_emails,
        ),
        linkedin_url=linkedin_url,
        hiring_signal_url=snapshot.url,
        outreach_channel="linkedin",
    )
    return apply_profile_enrichment(draft, profile=context.profile, post=snapshot)


def _profile_prompt_block(context: HiringSignalContext) -> str:
    profile = context.profile
    if profile is None:
        return "Profile metadata: not available"
    return f"""Profile metadata (from author profile page):
Name: {profile.person_name or "unknown"}
Headline: {profile.headline or "unknown"}
Company: {profile.company or "unknown"}
Profile URL: {profile.profile_url or "unknown"}"""


def extract_hiring_signal_draft(
    context: HiringSignalContext,
) -> tuple[HiringSignalDraft, bool]:
    """
    Extract a hiring signal draft from post (+ optional profile) context.

    Returns (draft, ai_ok). When OpenAI fails, returns a DOM fallback draft.
    """
    snapshot = context.post
    if client is None:
        return (
            _fallback_draft(context, reason="OpenAI unavailable; DOM fallback used."),
            False,
        )

    prompt = f"""
You extract hiring-signal metadata from a LinkedIn post for outreach logging.

Suggest only; fields may be unknown — use null or empty string.
Do not invent contact details not supported by the post text.
Do not generate outreach messages.
Only include application_emails that appear verbatim (or de-obfuscated) in the post text.

Allowed hiring_signal_type values:
- linkedin_hiring_post — company/recruiter hiring announcement
- founder_post — founder/executive hiring post

Post URL: {snapshot.url}
Author name: {snapshot.author_name or "unknown"}
Author profile URL: {snapshot.author_profile_url or "unknown"}

{_profile_prompt_block(context)}

Post text:
{snapshot.body_text}

For hiring_signal_notes, return 4–8 concise bullet strings (omit bullets when
information is absent — do not guess). Cover only what the post supports:
- Hiring context (why hiring / team growth)
- Role(s) mentioned
- Seniority clues
- Skills or experience requested
- Company or team context
- Urgency indicators
- Outreach angle (why this signal matters for outreach)

Return ONLY raw JSON with this shape:
{{
  "hiring_signal_type": "linkedin_hiring_post" | "founder_post" | null,
  "person_name": string | null,
  "company": string | null,
  "designation": string | null,
  "hiring_signal_notes": string[] | null,
  "application_emails": string[] | null,
  "application_instructions": string | null
}}
"""

    try:
        _ingest_debug("hiring_signal_extract: OpenAI request starting")
        response = client.responses.create(model=resolve_openai_model(), input=prompt)
        content = _strip_json_markdown(response.output_text)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        draft = parse_hiring_signal_draft_payload(parsed, context=context)
        _ingest_debug(f"hiring_signal_extract: parsed fields={list(parsed.keys())}")
        return draft, True
    except Exception as exc:
        _ingest_debug(f"hiring_signal_extract failed: {exc}")
        if debug_hiring_signal_ingest_enabled():
            traceback.print_exc()
        return (
            _fallback_draft(
                context,
                reason="AI extraction failed; review DOM fallback before saving.",
            ),
            False,
        )
