"""Load canonical candidate profile text for AI batch scoring."""

from __future__ import annotations

from pathlib import Path

import paths


def load_candidate_profile(*, path: Path | None = None) -> str:
    """
    Read candidate profile markdown from disk.

    Uses paths.ai_candidate_profile_path() unless path is provided.
    """
    profile_path = path if path is not None else paths.ai_candidate_profile_path()
    if not profile_path.is_file():
        raise FileNotFoundError(
            f"AI candidate profile not found: {profile_path}. "
            "Set AI_CANDIDATE_PROFILE_PATH or create config/profiles/ai_candidate_profile.example.md"
        )
    text = profile_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"AI candidate profile is empty: {profile_path}")
    return text
