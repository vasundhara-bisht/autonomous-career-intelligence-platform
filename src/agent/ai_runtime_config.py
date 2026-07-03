"""AI scoring runtime limits (env overrides with production defaults)."""

from __future__ import annotations

import os

DEFAULT_DEBUG_LIMIT = 300
DEFAULT_BATCH_SIZE = 15
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def resolve_debug_limit() -> int:
    """Max jobs sent to OpenAI per run. Override: DEBUG_LIMIT env (integer)."""
    raw = os.environ.get("DEBUG_LIMIT", "").strip()
    if raw:
        return int(raw)
    return DEFAULT_DEBUG_LIMIT


def resolve_openai_model() -> str:
    """OpenAI model to use for all AI calls. Override: OPENAI_MODEL env (model string)."""
    raw = os.environ.get("OPENAI_MODEL", "").strip()
    return raw if raw else DEFAULT_OPENAI_MODEL


def resolve_batch_size() -> int:
    """Jobs per OpenAI batch request. Override: BATCH_SIZE env (positive integer)."""
    raw = os.environ.get("BATCH_SIZE", "").strip()
    if not raw:
        return DEFAULT_BATCH_SIZE
    try:
        parsed = int(raw)
    except ValueError:
        print(
            f"⚠️ Invalid BATCH_SIZE={raw!r}; using default {DEFAULT_BATCH_SIZE}"
        )
        return DEFAULT_BATCH_SIZE
    if parsed < 1:
        print(
            f"⚠️ Invalid BATCH_SIZE={raw!r}; using default {DEFAULT_BATCH_SIZE}"
        )
        return DEFAULT_BATCH_SIZE
    return parsed
