from openai import OpenAI
import os
import json
import time
import traceback
import math
from typing import Any

from agent.ai_runtime_config import resolve_openai_model

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    api_key = api_key.strip()  # 🔥 CRITICAL FIX (removes \n, spaces)

client = OpenAI(api_key=api_key)

AI_DESCRIPTION_MAX_CHARS = 3000
AI_DESCRIPTION_MIN_CLEAN_CHARS = 200

_SECTION_MARKERS = (
    "about the role",
    "responsibilities",
    "what you'll do",
)


def prepare_description_for_scoring(raw_description: str) -> str:
    """Trim company fluff (section markers), preserve casing, cap for OpenAI prompt."""
    raw_desc = raw_description or ""
    desc_lower = raw_desc.lower()
    cleaned = raw_desc
    for marker in _SECTION_MARKERS:
        if marker in desc_lower:
            idx = desc_lower.index(marker) + len(marker)
            cleaned = raw_desc[idx:]
            break
    if len(cleaned) < AI_DESCRIPTION_MIN_CLEAN_CHARS:
        cleaned = raw_desc
    return cleaned[:AI_DESCRIPTION_MAX_CHARS]


def debug_ai_enabled() -> bool:
    return os.environ.get("DEBUG_AI", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _ai_debug(message: str) -> None:
    if debug_ai_enabled():
        print(message)


def normalize_ai_batch_response(parsed: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize provider responses into list[dict].
    Supports:
    - list[dict]
    - single dict item
    - wrapped dict structures: {"results":[...]} / {"items":[...]} / {"data":[...]}
    """
    meta: dict[str, Any] = {
        "normalization_strategy_used": "unknown",
        "parsed_result_count": 0,
        "raw_type": type(parsed).__name__,
    }
    if parsed is None:
        meta["normalization_strategy_used"] = "empty_none"
        return [], meta

    if isinstance(parsed, list):
        meta["normalization_strategy_used"] = "list_passthrough"
        meta["parsed_result_count"] = len(parsed)
        return parsed, meta

    if isinstance(parsed, dict):
        for key in ("results", "items", "data"):
            wrapped = parsed.get(key)
            if isinstance(wrapped, list):
                meta["normalization_strategy_used"] = f"wrapped_{key}_list"
                meta["parsed_result_count"] = len(wrapped)
                return wrapped, meta
        if all(k in parsed for k in ("index", "score", "reason")):
            meta["normalization_strategy_used"] = "single_dict_wrapped"
            meta["parsed_result_count"] = 1
            return [parsed], meta
        meta["normalization_strategy_used"] = "dict_unrecognized"
        return [], meta

    meta["normalization_strategy_used"] = "unsupported_type"
    return [], meta


def validate_ai_batch_results(
    results: list[dict[str, Any]], *, batch_size: int
) -> tuple[list[dict[str, Any]], int]:
    """Validate/coerce normalized AI results and skip malformed entries."""
    valid: list[dict[str, Any]] = []
    skipped = 0
    for item in results:
        if not isinstance(item, dict):
            skipped += 1
            continue
        if not all(k in item for k in ("index", "score", "reason")):
            skipped += 1
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if idx < 0 or idx >= batch_size:
            skipped += 1
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not math.isfinite(score):
            skipped += 1
            continue
        reason = str(item.get("reason") or "").strip()
        if not reason:
            skipped += 1
            continue
        valid.append({"index": idx, "score": score, "reason": reason})
    return valid, skipped


def batch_score_jobs(jobs, user_profile):
    job_text = ""

    for i, job in enumerate(jobs):
        raw_desc = job.get("description", "") or ""
        desc = prepare_description_for_scoring(raw_desc)

        job_text += f"""
Job {i}:
Title: {job.get("title", "")}
Company: {job.get("company", "")}
Location: {job.get("location", "")}
Description: {desc}

---
"""

    # 🔥 SMART PROMPT (UPGRADED)
    prompt = f"""
You are an expert career assistant evaluating Product Manager roles.

You MUST:
- Read the FULL job description
- Evaluate real responsibilities (NOT just title)
- Your reasoning MUST reference specific signals from the description (domain, responsibilities, or seniority)
- Avoid generic statements like "fits well" or "no red flags"
- If insufficient information is available in the description, explicitly state that instead of guessing
- Identify domain (fintech, SaaS, AI, etc.)
- Detect seniority carefully:
ACCEPT:
- Product Manager
- Senior Product Manager
- Product Manager II / III
- Lead Product Manager (treat as acceptable unless explicitly described as highly senior or leadership-heavy)

REJECT ONLY:
- Staff Product Manager
- Principal Product Manager
- Director / VP roles

- Senior Product Manager is VALID for this candidate (4.5 years experience) and should NOT be penalized. Do NOT assume senior roles are a bad fit unless explicitly requiring significantly more experience (e.g., 7+ years).
- When mentioning seniority in reasoning: Extract years if mentioned (e.g., "6–8 years", "6+ years"). If not mentioned, say "Not specified". Do NOT assume years unless explicitly written
- Penalize data-heavy / engineering-heavy roles
- Prefer B2B SaaS, fintech, AI roles
- Justify score using at least ONE of:
  - domain (fintech, SaaS, AI, etc.)
  - responsibilities (ownership, execution, strategy)
  - seniority alignment

Candidate Profile:
{user_profile}

Jobs:
{job_text}

Return ONLY raw JSON.
Do NOT wrap the response in markdown or ```json```.
Do NOT include explanation outside JSON.

Each item must follow:
{{
  "index": <job_index>,
  "score": <0-10>,
  "reason": "<specific explanation referencing domain, responsibilities, and seniority>"
}}

Scoring:
9-10 → Strong fit  
7-8 → Good fit  
5-6 → Weak fit  
0-4 → Reject
"""

    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        try:
            _ai_debug("\n" + "=" * 60)
            _ai_debug("🤖 [debug] OpenAI batch request starting")
            _ai_debug("=" * 60)

            response = client.responses.create(
                model=resolve_openai_model(),
                input=prompt
            )

            _ai_debug("=" * 60)
            _ai_debug("✅ [debug] OpenAI response received")
            _ai_debug("=" * 60)

            content = response.output_text.strip()

            # 🔧 CLEAN MARKDOWN (fix ```json issue)
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            # 🔧 CLEAN BAD CHARACTERS
            content = content.replace("“", '"').replace("”", '"')

            # 🔧 SAFE JSON PARSE
            try:
                parsed = json.loads(content)
            except Exception:
                _ai_debug("❌ [debug] JSON parse failed — skipping batch")
                if debug_ai_enabled():
                    traceback.print_exc()
                return {
                    "results": [],
                    "parsed_result_count": 0,
                    "normalization_strategy_used": "json_parse_failed",
                    "raw_type": "parse_error",
                    "request_ok": False,
                }

            normalized, norm_meta = normalize_ai_batch_response(parsed)
            return {
                "results": normalized,
                "parsed_result_count": int(norm_meta.get("parsed_result_count", 0)),
                "normalization_strategy_used": str(
                    norm_meta.get("normalization_strategy_used", "unknown")
                ),
                "raw_type": str(norm_meta.get("raw_type", "unknown")),
                "request_ok": True,
            }

        except Exception as e:
            _ai_debug(f"\n⚠️ [debug] AI attempt {attempt + 1} failed")
            _ai_debug(f"[debug] ERROR TYPE: {type(e)}")
            _ai_debug(f"[debug] ERROR MESSAGE: {e}")
            if debug_ai_enabled():
                traceback.print_exc()

            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))  # backoff
            else:
                _ai_debug("❌ [debug] AI failed after retries")
                return {
                    "results": [],
                    "parsed_result_count": 0,
                    "normalization_strategy_used": "request_failed",
                    "raw_type": "request_error",
                    "request_ok": False,
                }