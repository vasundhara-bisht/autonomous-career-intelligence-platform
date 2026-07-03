"""Tests for dashboard monitor presentation labels."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from monitor_display import (  # noqa: E402
    badge_tone_for_monitor_health,
    budget_exhausted_skip_caption,
    classify_status_banner,
    format_budget_usage,
    format_deferral_summary,
    present_auth_health,
    present_latest_monitor_overview,
    present_monitor_health,
    present_next_retry,
    present_overall_login_health,
    present_provider_login_health,
    present_provider_health_detail,
    present_reason_code,
    present_run_status,
    present_scheduler_state,
    present_systemic_alert,
    render_status_badge,
    summarize_run_skip_issues,
)


def _snapshot(**kwargs):
    from db.read.monitor_provider_metrics import ProviderMonitorSnapshot

    defaults = {
        "login_health": "ok",
        "login_reason": "auth:ok",
        "login_applicable_this_run": True,
        "checks_today": 0,
        "budget_cap_per_day": 150,
        "budget_remaining": 150,
        "jobs_needing_attention": 0,
        "jobs_paused": 0,
        "eligible_monitor_queue": 0,
        "provider_state": None,
    }
    defaults.update(kwargs)
    return ProviderMonitorSnapshot(**defaults)


class MonitorDisplayLabelTests(unittest.TestCase):
    def test_present_systemic_alert_maps_known_values(self) -> None:
        self.assertEqual(present_systemic_alert("high_check_failed_rate"), "High failure rate")
        self.assertEqual(present_systemic_alert("provider_protection"), "Protection detected")
        self.assertEqual(present_systemic_alert("none"), "None")

    def test_present_auth_health_maps_known_values(self) -> None:
        self.assertEqual(present_auth_health("ok"), "Connected")
        self.assertEqual(present_auth_health("degraded"), "Needs attention")

    def test_present_monitor_health_maps_known_values(self) -> None:
        self.assertEqual(present_monitor_health("ok"), "Healthy")
        self.assertEqual(present_monitor_health("degraded"), "Degraded")

    def test_present_reason_code_humanizes_prefix(self) -> None:
        self.assertEqual(present_reason_code("auth:login_wall"), "Login: Login Wall")

    def test_present_scheduler_state_operator_paused(self) -> None:
        self.assertEqual(
            present_scheduler_state("running", operator_paused=True),
            "Paused by operator",
        )
        self.assertEqual(present_scheduler_state("not_loaded"), "Not loaded")

    def test_present_provider_health_detail_includes_reason(self) -> None:
        label = present_provider_health_detail(
            {"health": "protection", "reason": "protection:unusual_activity"}
        )
        self.assertIn("Protection active", label)
        self.assertIn("Protection", label)

    def test_present_provider_health_detail_defaults_to_healthy(self) -> None:
        self.assertEqual(present_provider_health_detail(None), "Healthy")

    def test_summarize_run_skip_issues_linkedin(self) -> None:
        lines = summarize_run_skip_issues(
            {"linkedin_skipped_limit": 3, "instahyre_skipped_limit": 9},
            source="linkedin",
        )
        self.assertEqual(lines, ["3 jobs not checked (daily limit reached)"])

    def test_summarize_run_skip_issues_empty_when_healthy(self) -> None:
        self.assertEqual(summarize_run_skip_issues({}, source="linkedin"), [])

    def test_present_next_retry_hides_when_healthy(self) -> None:
        show, label = present_next_retry({"health": "ok"}, format_timestamp=lambda _: "—")
        self.assertFalse(show)
        self.assertEqual(label, "")

    def test_present_next_retry_ready_when_limited_without_timestamp(self) -> None:
        show, label = present_next_retry({"health": "degraded"}, format_timestamp=lambda _: "—")
        self.assertTrue(show)
        self.assertEqual(label, "Ready")

    def test_present_next_retry_shows_timestamp(self) -> None:
        show, label = present_next_retry(
            {"health": "degraded", "backoff_until": "2026-06-27T12:00:00"},
            format_timestamp=lambda _: "27 Jun 2026 · 12:00 PM",
        )
        self.assertTrue(show)
        self.assertEqual(label, "27 Jun 2026 · 12:00 PM")

    def test_format_deferral_summary_uses_labels(self) -> None:
        text = format_deferral_summary({"linkedin_skipped_auth": 2})
        self.assertIn("LinkedIn skipped (authentication)", text)
        self.assertIn("2", text)

    def test_present_run_status_maps_completed(self) -> None:
        self.assertEqual(present_run_status("completed"), "Completed")

    def test_present_run_status_maps_skipped_budget_exhausted(self) -> None:
        self.assertEqual(
            present_run_status("skipped_budget_exhausted"),
            "Skipped (Budget Exhausted)",
        )

    def test_present_latest_monitor_overview_uses_status_for_budget_skip(self) -> None:
        label = present_latest_monitor_overview(
            {"status": "skipped_budget_exhausted", "monitor_health": "ok"},
        )
        self.assertEqual(label, "Skipped (Budget Exhausted)")

    def test_present_latest_monitor_overview_uses_health_for_completed(self) -> None:
        label = present_latest_monitor_overview(
            {"status": "completed", "monitor_health": "ok"},
        )
        self.assertEqual(label, "Healthy")

    def test_budget_exhausted_skip_caption_is_operator_friendly(self) -> None:
        self.assertIn("monitoring budget", budget_exhausted_skip_caption().lower())

    def test_render_status_badge_includes_tone_class(self) -> None:
        html = render_status_badge("Connected", "ok")
        self.assertIn("mon-badge-ok", html)
        self.assertIn("Connected", html)

    def test_format_budget_usage(self) -> None:
        self.assertEqual(format_budget_usage(140, 500), "140 / 500")

    def test_present_overall_login_worst_case(self) -> None:
        snapshots = {
            "linkedin": _snapshot(source="linkedin"),
            "instahyre": _snapshot(
                source="instahyre",
                login_health="degraded",
                login_reason="auth:login_wall",
                budget_cap_per_day=500,
                budget_remaining=500,
            ),
        }
        label, tone = present_overall_login_health(snapshots)
        self.assertEqual(label, "Needs attention")
        self.assertEqual(tone, "error")

    def test_present_overall_login_excludes_instahyre_when_not_applicable(self) -> None:
        snapshots = {
            "linkedin": _snapshot(source="linkedin"),
            "instahyre": _snapshot(
                source="instahyre",
                login_health="degraded",
                login_reason="probe:bot_protection",
                login_applicable_this_run=False,
                budget_cap_per_day=500,
                budget_remaining=500,
            ),
        }
        label, tone = present_overall_login_health(snapshots)
        self.assertEqual(label, "Connected")
        self.assertEqual(tone, "ok")

    def test_present_provider_login_neutral_when_instahyre_not_applicable(self) -> None:
        snapshot = _snapshot(
            source="instahyre",
            login_health="degraded",
            login_reason="probe:bot_protection",
            login_applicable_this_run=False,
            budget_cap_per_day=500,
            budget_remaining=500,
        )
        label, tone = present_provider_login_health(snapshot)
        self.assertEqual(label, "Not verified this run")
        self.assertEqual(tone, "neutral")

    def test_classify_status_banner_skips_instahyre_when_not_applicable(self) -> None:
        snapshots = {
            "instahyre": _snapshot(
                source="instahyre",
                login_health="degraded",
                login_reason="auth:http_403",
                login_applicable_this_run=False,
                budget_cap_per_day=500,
                budget_remaining=500,
            ),
        }
        banner = classify_status_banner(
            {"status": "completed", "monitor_health": "ok", "systemic_alert": "none"},
            snapshots,
        )
        self.assertNotEqual(banner.level, "red")
        self.assertNotIn("Refresh the InstaHyre session", banner.message)

    def test_classify_status_banner_red_on_instahyre_login_degraded(self) -> None:
        snapshots = {
            "instahyre": _snapshot(
                source="instahyre",
                login_health="degraded",
                login_reason="auth:http_403",
                budget_cap_per_day=500,
                budget_remaining=500,
            ),
        }
        banner = classify_status_banner(
            {"status": "completed", "monitor_health": "ok", "systemic_alert": "none"},
            snapshots,
        )
        self.assertEqual(banner.level, "red")
        self.assertIn("InstaHyre login verification failed", banner.message)
        self.assertIn("Refresh the InstaHyre session", banner.message)
        self.assertNotIn("resume", banner.message.lower())

    def test_classify_status_banner_skips_instahyre_refresh_on_probe_bot_protection(self) -> None:
        snapshots = {
            "instahyre": _snapshot(
                source="instahyre",
                login_health="degraded",
                login_reason="probe:bot_protection",
                budget_cap_per_day=500,
                budget_remaining=500,
            ),
        }
        banner = classify_status_banner(
            {"status": "completed", "monitor_health": "ok", "systemic_alert": "none"},
            snapshots,
        )
        self.assertNotEqual(banner.level, "red")
        self.assertNotIn("Refresh the InstaHyre session", banner.message)

    def test_classify_status_banner_red_on_linkedin_login_degraded(self) -> None:
        snapshots = {
            "linkedin": _snapshot(
                source="linkedin",
                login_health="degraded",
                login_reason="auth:login_wall",
            ),
        }
        banner = classify_status_banner(
            {"status": "completed", "monitor_health": "ok", "systemic_alert": "none"},
            snapshots,
        )
        self.assertIn("LinkedIn login verification failed", banner.message)
        self.assertNotIn("resume", banner.message.lower())

    def test_classify_status_banner_orange_on_budget_exhausted_with_jobs(self) -> None:
        snapshots = {
            "linkedin": _snapshot(
                source="linkedin",
                checks_today=150,
                budget_remaining=0,
                jobs_needing_attention=3,
            ),
        }
        banner = classify_status_banner(
            {"status": "completed", "monitor_health": "ok", "systemic_alert": "none"},
            snapshots,
        )
        self.assertEqual(banner.level, "orange")

    def test_classify_status_banner_all_clear_when_parity_summary_is_none_sentinel(self) -> None:
        banner = classify_status_banner(
            {
                "status": "completed",
                "monitor_health": "ok",
                "systemic_alert": "none",
                "parity_warning_summary": "none",
            },
            {},
        )
        self.assertEqual(banner.level, "green")
        self.assertEqual(banner.message, "All clear — monitor health looks good.")
        self.assertEqual(banner.details, ())

    def test_classify_status_banner_orange_on_real_parity_warning(self) -> None:
        banner = classify_status_banner(
            {
                "status": "completed",
                "monitor_health": "ok",
                "systemic_alert": "none",
                "parity_warning_summary": (
                    "cohort completeness gap for run_id=31: checked_count=7 < cohort_size=10"
                ),
            },
            {},
        )
        self.assertEqual(banner.level, "orange")
        self.assertIn("Data parity review recommended", banner.details[0])

    def test_badge_tone_for_monitor_health_budget_skip(self) -> None:
        self.assertEqual(
            badge_tone_for_monitor_health({"status": "skipped_budget_exhausted"}),
            "warn",
        )


if __name__ == "__main__":
    unittest.main()
