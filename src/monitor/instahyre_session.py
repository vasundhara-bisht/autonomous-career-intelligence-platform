"""InstaHyre session fetch evaluation for lifecycle monitor auth probe."""

from __future__ import annotations

from urllib.parse import urlparse

from monitor.classifiers.text import html_to_text

INSTAHYRE_LOGIN_MARKERS = (
    "log in to instahyre",
    "login to instahyre",
    "sign in to instahyre",
    "please log in",
    "please sign in",
)

INSTAHYRE_PROFILE_SHELL_MARKERS = (
    "candidate-profile",
    "profile-name",
    "sign out",
)

INSTAHYRE_BOT_PROTECTION_MARKERS = (
    "just a moment",
    "challenges.cloudflare.com",
    "cf-browser-verification",
    "checking your browser",
)

_CANDIDATE_SESSION_PATH_PREFIXES: tuple[str, ...] = (
    "/candidate/opportunities",
    "/candidate/profile",
    "/candidate/search-jobs",
    "/candidate/job-detail/",
    "/search-jobs",
)

_RECRUITER_SESSION_PATH_MARKERS: tuple[str, ...] = (
    "/employer/",
    "/recruiters/",
    "/hiring/dashboard",
)


def is_valid_candidate_session_url(url: str) -> bool:
    """True when the final URL is a candidate-authenticated InstaHyre surface."""
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    if "/login" in path:
        return False
    if any(marker in path for marker in _RECRUITER_SESSION_PATH_MARKERS):
        return False
    if any(path.startswith(prefix) for prefix in _CANDIDATE_SESSION_PATH_PREFIXES):
        return True
    if path.startswith("/job-"):
        return True
    return False


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _is_bot_protection_page(html: str, body_text: str) -> bool:
    combined = f"{html}\n{body_text}".lower()
    return any(marker in combined for marker in INSTAHYRE_BOT_PROTECTION_MARKERS)


def evaluate_instahyre_session_fetch(
    *,
    final_url: str,
    status_code: int | None,
    html: str,
) -> tuple[str, str]:
    """Classify an InstaHyre session probe fetch as ok or degraded."""
    body_text = html_to_text(html)
    lowered_url = final_url.lower()
    has_login_markers = _has_marker(body_text, INSTAHYRE_LOGIN_MARKERS)
    has_profile_shell = _has_marker(f"{html}\n{body_text}", INSTAHYRE_PROFILE_SHELL_MARKERS)
    http_status = status_code or 0

    if has_login_markers or "/login" in lowered_url:
        return "degraded", "auth:login_wall"

    if _is_bot_protection_page(html, body_text):
        return "degraded", "probe:bot_protection"

    if has_profile_shell:
        return "ok", "auth:ok"

    if is_valid_candidate_session_url(final_url) and http_status not in (401, 403):
        return "ok", "auth:ok"

    if http_status == 401:
        return "degraded", "auth:http_401"
    if http_status == 403:
        return "degraded", "auth:http_403"
    if http_status >= 500:
        return "degraded", f"auth:http_{http_status}"

    return "degraded", "auth:session_invalid"
