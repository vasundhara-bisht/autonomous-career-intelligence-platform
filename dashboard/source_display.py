"""Human-readable labels for acquisition source keys (display only)."""

from __future__ import annotations

SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "linkedin": "LinkedIn",
    "instahyre": "InstaHyre",
    "lever": "Lever",
    "greenhouse": "Greenhouse",
    "weworkremotely": "WeWorkRemotely",
}


def source_display_name(source_key: object) -> str:
    """Map a stored source key to a user-visible label; unknown keys pass through."""
    raw = str(source_key or "").strip()
    if not raw:
        return ""
    mapped = SOURCE_DISPLAY_NAMES.get(raw.lower())
    if mapped:
        return mapped
    return raw
