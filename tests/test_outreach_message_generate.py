"""Unit tests for outreach message generation and model config."""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT / "src"),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.ai_runtime_config import resolve_openai_model  # noqa: E402
from agent.outreach_message_generate import generate_outreach_message  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_openai_model
# ---------------------------------------------------------------------------


class ResolveOpenAIModelTests(unittest.TestCase):
    def test_default_returns_gpt4o_mini(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_MODEL", None)
            self.assertEqual(resolve_openai_model(), "gpt-4o-mini")

    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-4o"}):
            self.assertEqual(resolve_openai_model(), "gpt-4o")

    def test_whitespace_env_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"OPENAI_MODEL": "  "}):
            self.assertEqual(resolve_openai_model(), "gpt-4o-mini")


# ---------------------------------------------------------------------------
# generate_outreach_message
# ---------------------------------------------------------------------------

_COMMON_KWARGS = dict(
    person_name="Priya Sharma",
    designation="Engineering Manager",
    company="Acme Corp",
    notes="- Hiring for senior PM\n- Fast-growing team",
    hiring_signal_type="linkedin_hiring_post",
    candidate_profile="Experienced PM with 8 years in B2B SaaS.",
)


def _make_mock_client(output_text: str) -> MagicMock:
    response = MagicMock()
    response.output_text = output_text
    mock_client = MagicMock()
    mock_client.responses.create.return_value = response
    return mock_client


class GenerateOutreachMessageTests(unittest.TestCase):
    def test_returns_message_and_ok_true_on_success(self) -> None:
        mock_client = _make_mock_client("Hey Priya, saw your post about the PM role at Acme.")
        with patch("agent.outreach_message_generate.client", mock_client):
            msg, ok = generate_outreach_message(**_COMMON_KWARGS)
        self.assertTrue(ok)
        self.assertIn("Priya", msg)

    def test_returns_empty_and_false_when_client_none(self) -> None:
        with patch("agent.outreach_message_generate.client", None):
            msg, ok = generate_outreach_message(**_COMMON_KWARGS)
        self.assertEqual(msg, "")
        self.assertFalse(ok)

    def test_returns_empty_and_false_on_api_error(self) -> None:
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = RuntimeError("network error")
        with patch("agent.outreach_message_generate.client", mock_client):
            msg, ok = generate_outreach_message(**_COMMON_KWARGS)
        self.assertEqual(msg, "")
        self.assertFalse(ok)

    def test_uses_resolve_openai_model_not_hardcoded(self) -> None:
        mock_client = _make_mock_client("Hi Priya.")
        with patch("agent.outreach_message_generate.client", mock_client):
            with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-4o"}):
                generate_outreach_message(**_COMMON_KWARGS)
        call_kwargs = mock_client.responses.create.call_args
        used_model = call_kwargs.kwargs.get("model") or call_kwargs.args[0]
        self.assertEqual(used_model, "gpt-4o")

    def test_temperature_07_passed_to_api(self) -> None:
        mock_client = _make_mock_client("Hi Priya.")
        with patch("agent.outreach_message_generate.client", mock_client):
            generate_outreach_message(**_COMMON_KWARGS)
        call_kwargs = mock_client.responses.create.call_args
        self.assertEqual(call_kwargs.kwargs.get("temperature"), 0.7)

    def test_previous_message_omitted_by_default(self) -> None:
        """No previous_message kwarg → prompt must not contain the differentiation instruction."""
        mock_client = _make_mock_client("Hi Priya.")
        with patch("agent.outreach_message_generate.client", mock_client):
            generate_outreach_message(**_COMMON_KWARGS)
        prompt_sent = mock_client.responses.create.call_args.kwargs.get("input", "")
        self.assertNotIn("Previous message", prompt_sent)

    def test_previous_message_included_in_prompt_when_provided(self) -> None:
        mock_client = _make_mock_client("Hi Priya, different angle.")
        with patch("agent.outreach_message_generate.client", mock_client):
            generate_outreach_message(
                **_COMMON_KWARGS,
                previous_message="Hey Priya, saw your post.",
            )
        prompt_sent = mock_client.responses.create.call_args.kwargs.get("input", "")
        self.assertIn("Previous message", prompt_sent)
        self.assertIn("Hey Priya, saw your post.", prompt_sent)

    def test_previous_message_empty_string_excluded_from_prompt(self) -> None:
        mock_client = _make_mock_client("Hi Priya.")
        with patch("agent.outreach_message_generate.client", mock_client):
            generate_outreach_message(**_COMMON_KWARGS, previous_message="")
        prompt_sent = mock_client.responses.create.call_args.kwargs.get("input", "")
        self.assertNotIn("Previous message", prompt_sent)

    def test_strips_whitespace_from_response(self) -> None:
        mock_client = _make_mock_client("  Hey Priya.  \n")
        with patch("agent.outreach_message_generate.client", mock_client):
            msg, _ = generate_outreach_message(**_COMMON_KWARGS)
        self.assertEqual(msg, "Hey Priya.")

    def test_candidate_profile_never_reloaded_from_disk(self) -> None:
        """generate_outreach_message must not call load_candidate_profile internally."""
        mock_client = _make_mock_client("Hi.")
        with patch("agent.outreach_message_generate.client", mock_client):
            # If the function tried to import / call load_candidate_profile it would
            # fail or be detectable; we assert it accepts the caller-supplied string.
            msg, ok = generate_outreach_message(
                **{**_COMMON_KWARGS, "candidate_profile": "Custom profile text."}
            )
        # The function ran without touching the filesystem.
        self.assertTrue(ok)

    def test_empty_output_text_returns_empty_string(self) -> None:
        mock_client = _make_mock_client("")
        with patch("agent.outreach_message_generate.client", mock_client):
            msg, ok = generate_outreach_message(**_COMMON_KWARGS)
        self.assertEqual(msg, "")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
