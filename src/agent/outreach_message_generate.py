"""OpenAI-assisted outreach message generation for Outreach Intelligence."""

from __future__ import annotations

import os
import traceback

from openai import OpenAI

from agent.ai_runtime_config import resolve_openai_model

api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    api_key = api_key.strip()
client = OpenAI(api_key=api_key) if api_key else None

_BANNED_PHRASES = (
    "I hope you're doing well",
    "I wanted to reach out",
    "I came across your post",
    "Dear ",
    "\u2014",  # em dash
)

_SYSTEM_PROMPT = """\
You write short LinkedIn outreach messages for an experienced product manager.

Every message must follow this exact format and structure — no exceptions:

Hi <recipient first name only>,

<Opening: 1 sentence — a personalized, specific observation about the hiring signal, recruiter, founder, company, or role.>
<Relevance: 1–2 sentences — why this sender is a natural fit, tied directly to what the role or company needs.>
<Differentiator: 1 sentence — one concrete PM-related strength or experience that stands out. Specific, not generic.>

<CTA: 1 sentence — a soft, direct ask. Open to a quick chat, share thoughts, or connect briefly. Mandatory.>

Regards,
Vasundhara Bisht

Rules:
- Greeting is mandatory. Use the recipient's first name only. Never omit.
- CTA is mandatory. Never omit.
- Signoff is mandatory. It must be exactly two lines: "Regards," on its own line, then "Vasundhara Bisht" on the next. Never omit.
- 60 to 120 words for the body (everything between the greeting and the signoff). If trimming is needed, shorten the body — never cut the CTA, greeting, or signoff.
- Casual but professional tone. Direct and specific.
- Do not use: em dashes, "I hope you're doing well", "I wanted to reach out", \
"I came across your post", "Dear", or any generic networking opener.
- Do not use filler phrases or AI-sounding language.
- Sound like a real person with a genuine reason to connect.
- Reference the hiring context concisely — show you read it, but don't quote it verbatim.
- Return ONLY the message text. No subject line, no additional label, no markdown.
"""


def _build_prompt(
    *,
    person_name: str,
    designation: str,
    company: str,
    notes: str,
    hiring_signal_type: str,
    candidate_profile: str,
    previous_message: str = "",
) -> str:
    signal_label = {
        "linkedin_hiring_post": "LinkedIn hiring post",
        "founder_post": "founder/executive post about hiring",
        "recruiter_message": "recruiter outreach",
        "whatsapp_referral": "WhatsApp referral",
        "personal_referral": "personal referral",
        "mentor_referral": "mentor referral",
        "direct_outreach": "direct outreach",
    }.get(hiring_signal_type, hiring_signal_type or "hiring signal")

    parts = [
        f"Recipient name: {person_name or 'unknown'}",
        f"Recipient designation: {designation or 'unknown'}",
        f"Company: {company or 'unknown'}",
        f"Signal type: {signal_label}",
    ]
    if notes:
        parts.append(f"Hiring signal notes:\n{notes}")
    if candidate_profile:
        parts.append(
            f"Sender profile (use to personalise — do not reproduce verbatim):\n{candidate_profile}"
        )
    if previous_message:
        parts.append(
            "Previous message (generate a meaningfully different version — "
            "use a different opening, observation, framing, and CTA style; "
            f"do not paraphrase):\n{previous_message}"
        )

    return "\n\n".join(parts)


def generate_outreach_message(
    *,
    person_name: str,
    designation: str,
    company: str,
    notes: str,
    hiring_signal_type: str,
    candidate_profile: str,
    previous_message: str = "",
) -> tuple[str, bool]:
    """
    Generate a recommended LinkedIn outreach message.

    Returns (message, ai_ok). When OpenAI is unavailable or fails,
    returns ("", False). The caller is responsible for supplying
    candidate_profile from session state — this function never reads from disk.

    Pass previous_message when regenerating so the model produces a
    meaningfully different version rather than rephrasing the same draft.
    """
    if client is None:
        return ("", False)

    prompt = _build_prompt(
        person_name=person_name,
        designation=designation,
        company=company,
        notes=notes,
        hiring_signal_type=hiring_signal_type,
        candidate_profile=candidate_profile,
        previous_message=previous_message,
    )

    try:
        response = client.responses.create(
            model=resolve_openai_model(),
            instructions=_SYSTEM_PROMPT,
            input=prompt,
            temperature=0.7,
        )
        message = (response.output_text or "").strip()
        return (message, True)
    except Exception:
        if os.getenv("DEBUG_OUTREACH_MESSAGE"):
            traceback.print_exc()
        return ("", False)
