"""Tests for AI scoring cap and batch size env resolution."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_REPO_ROOT = __file__
for _ in range(2):
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from agent.ai_runtime_config import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_DEBUG_LIMIT,
    resolve_batch_size,
    resolve_debug_limit,
)


class ResolveDebugLimitTests(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEBUG_LIMIT", None)
            self.assertEqual(resolve_debug_limit(), DEFAULT_DEBUG_LIMIT)
            self.assertEqual(DEFAULT_DEBUG_LIMIT, 300)

    def test_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"DEBUG_LIMIT": "50"}):
            self.assertEqual(resolve_debug_limit(), 50)


class ResolveBatchSizeTests(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BATCH_SIZE", None)
            self.assertEqual(resolve_batch_size(), DEFAULT_BATCH_SIZE)
            self.assertEqual(DEFAULT_BATCH_SIZE, 15)

    def test_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"BATCH_SIZE": "20"}):
            self.assertEqual(resolve_batch_size(), 20)

    def test_invalid_falls_back_to_default(self) -> None:
        with mock.patch.dict(os.environ, {"BATCH_SIZE": "abc"}):
            self.assertEqual(resolve_batch_size(), DEFAULT_BATCH_SIZE)

    def test_zero_falls_back_to_default(self) -> None:
        with mock.patch.dict(os.environ, {"BATCH_SIZE": "0"}):
            self.assertEqual(resolve_batch_size(), DEFAULT_BATCH_SIZE)


if __name__ == "__main__":
    unittest.main()
