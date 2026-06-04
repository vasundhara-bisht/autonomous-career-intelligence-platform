"""Production logging helpers for Instahyre acquisition (DEBUG_INSTAHYRE gated)."""

from __future__ import annotations

import os
import traceback
from typing import Any


def debug_instahyre_enabled() -> bool:
    return os.environ.get("DEBUG_INSTAHYRE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def debug_dom_enabled() -> bool:
    return debug_instahyre_enabled() or os.environ.get(
        "INSTAHYRE_DEBUG_DOM", ""
    ).strip().lower() in ("1", "true", "yes", "on")


def log_ok(message: str) -> None:
    print(message)


def log_warn(message: str) -> None:
    print(message)


def log_fail(message: str) -> None:
    print(message)


def log_debug(message: str) -> None:
    if debug_instahyre_enabled():
        print(message)


def log_debug_rejection(reason: str, **fields: Any) -> None:
    if not debug_instahyre_enabled():
        return
    parts = " ".join(f"{k}={v!r}" for k, v in fields.items())
    print(f"  [debug] instahyre_rejected reason={reason} {parts}".rstrip())


def log_feed_debug_metrics(metrics: dict[str, Any]) -> None:
    if not debug_instahyre_enabled():
        return
    print("  [debug] instahyre_feed_metrics:")
    for key, value in metrics.items():
        if key == "cards_after_each_scroll":
            print(f"    {key}={value}")
            continue
        if key == "scroll_cycle_details":
            print(f"    {key}:")
            for entry in value or []:
                print(f"      - {entry}")
            continue
        if key == "strategy_fallback_chains":
            print(f"    {key}:")
            for chain in value or []:
                print(f"      cycle {chain.get('cycle')}:")
                for attempt in chain.get("attempts") or []:
                    print(f"        - {attempt}")
            continue
        if key == "page_traversal_details":
            print(f"    {key}:")
            for entry in value or []:
                print(f"      - {entry}")
            continue
        if key == "cards_per_page":
            print(f"    {key}={value}")
            continue
        print(f"    {key}={value}")


def log_failure_with_trace(context: str, exc: BaseException) -> None:
    log_fail(f"❌ {context}: {exc}")
    if debug_instahyre_enabled():
        traceback.print_exc()
