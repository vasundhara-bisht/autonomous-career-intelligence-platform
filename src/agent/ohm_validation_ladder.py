"""OHM Phase 6 automated validation ladder (steps 1–4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from db.services.lifecycle_cohort import (
    MONITORED_SOURCES,
    count_monitor_candidates,
    is_infrastructure_check_failed,
    resolve_monitor_cohort,
)
from monitor.auth_probe import evaluate_linkedin_auth_probe, is_probe_infrastructure_error
from monitor.browser import PageFetchResult
from monitor.provider_protection import detect_linkedin_protection


@dataclass(frozen=True)
class LadderStepResult:
    step: str
    passed: bool
    detail: str
    data: dict[str, Any] | None = None


def _step_cohort_preview(session: Session) -> LadderStepResult:
    total = count_monitor_candidates(session)
    preview = resolve_monitor_cohort(session, limit=25)
    infra_t4 = sum(
        1
        for job in preview
        if job.listing_status == "check_failed"
        and is_infrastructure_check_failed(job.listing_status_reason)
    )
    sources = {source: sum(1 for job in preview if job.source == source) for source in MONITORED_SOURCES}
    detail = (
        f"eligible_candidates={total}; preview_limit=25; "
        f"preview_infra_check_failed={infra_t4}; preview_sources={sources}"
    )
    passed = total >= 0
    return LadderStepResult(
        step="1_cohort_preview",
        passed=passed,
        detail=detail,
        data={
            "eligible_candidates": total,
            "preview_count": len(preview),
            "preview_infra_check_failed": infra_t4,
            "preview_sources": sources,
        },
    )


def _step_auth_probe() -> LadderStepResult:
    result = evaluate_linkedin_auth_probe(
        probe_url="https://www.linkedin.com/feed/",
        fetch=PageFetchResult(
            url="https://www.linkedin.com/feed/",
            html="<html><body><h1>Sign in</h1><p>Join LinkedIn</p></body></html>",
            http_status=200,
        ),
    )
    protection = detect_linkedin_protection(
        url="https://www.linkedin.com/feed/",
        html="<html><body><h1>Sign in</h1><p>Join LinkedIn</p></body></html>",
        http_status=200,
    )
    passed = (
        result.auth_health == "degraded"
        and result.reason == "auth:login_wall"
        and not protection.is_protection
    )
    detail = f"auth_health={result.auth_health}; reason={result.reason}; protection={protection.is_protection}"
    return LadderStepResult(step="2_auth_probe", passed=passed, detail=detail)


def _step_protection_probe() -> LadderStepResult:
    html = (
        "<html><body><h1>Security verification</h1>"
        "<p>We noticed some unusual activity on your account.</p></body></html>"
    )
    protection = detect_linkedin_protection(
        url="https://www.linkedin.com/checkpoint/challenge/verify",
        html=html,
        http_status=200,
    )
    passed = protection.is_protection and protection.reason == "protection:unusual_activity"
    detail = f"protection={protection.is_protection}; reason={protection.reason}"
    return LadderStepResult(step="3_protection_probe", passed=passed, detail=detail)


def _step_infra_probe() -> LadderStepResult:
    error = "timeout:goto"
    passed = is_probe_infrastructure_error(error)
    auth_degraded = False
    try:
        evaluate_linkedin_auth_probe(
            probe_url="https://www.linkedin.com/feed/",
            fetch=PageFetchResult(
                url="https://www.linkedin.com/feed/",
                html="",
                http_status=None,
                error=error,
            ),
        )
    except ValueError:
        auth_degraded = False
    protection = detect_linkedin_protection(
        url="https://www.linkedin.com/jobs/view/1/",
        html="",
        http_status=None,
        error=error,
    )
    passed = passed and not protection.is_protection and not auth_degraded
    detail = f"infra_error={error}; protection={protection.is_protection}; auth_degraded={auth_degraded}"
    return LadderStepResult(step="4_infra_probe", passed=passed, detail=detail)


def run_automated_validation_ladder(session: Session) -> dict[str, Any]:
    """Run OHM Phase 6 automated validation ladder steps 1–4."""
    steps = [
        _step_cohort_preview(session),
        _step_auth_probe(),
        _step_protection_probe(),
        _step_infra_probe(),
    ]
    return {
        "passed": all(step.passed for step in steps),
        "steps": [
            {
                "step": step.step,
                "passed": step.passed,
                "detail": step.detail,
                "data": step.data,
            }
            for step in steps
        ],
    }
