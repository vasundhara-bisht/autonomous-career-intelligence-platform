#!/usr/bin/env python3
"""Debug InstaHyre auth probe — profile page session check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.browser import MonitorBrowser
from monitor.instahyre_auth_probe import instahyre_auth_probe_url, run_instahyre_auth_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Run InstaHyre auth probe for debugging.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    args = parser.parse_args()

    probe_url = instahyre_auth_probe_url()
    with MonitorBrowser() as browser:
        result = run_instahyre_auth_probe(browser.fetch_job_page)

    payload = {
        "probe_url": probe_url,
        "auth_health": result.auth_health,
        "reason": result.reason,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("InstaHyre auth probe")
        print(f"  probe_url:   {probe_url}")
        print(f"  auth_health: {result.auth_health}")
        print(f"  reason:      {result.reason}")

    return 0 if result.auth_health == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
