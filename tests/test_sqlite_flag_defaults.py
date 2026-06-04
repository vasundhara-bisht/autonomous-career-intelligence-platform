"""D8B remediation: canonical sqlite_flag defaults and explicit off behavior."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_SQLITE_ENV_KEYS = (
    "SQLITE_ENABLED",
    "SQLITE_DUAL_WRITE",
    "SQLITE_READ",
    "SQLITE_PIPELINE_READ",
    "SQLITE_QUERY_STATE_READ",
    "SQLITE_WRITE_PRIMARY",
    "SQLITE_EXPORT_JOBS_CSV",
    "SQLITE_EXPORT_HISTORICAL_CSV",
    "SQLITE_EXPORT_DESCRIPTIONS_CSV",
    "SQLITE_EXPORT_CRM_CSV",
    "SQLITE_DASHBOARD_WRITE",
    "SQLITE_EXPORT_FROM_DB",
    "SQLITE_METADATA_HARD_PARITY",
)


class SqliteFlagDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in _SQLITE_ENV_KEYS}
        for k in _SQLITE_ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_d8b_defaults_on_without_env(self) -> None:
        from db.config import sqlite_flag

        self.assertTrue(sqlite_flag("SQLITE_ENABLED"))
        self.assertTrue(sqlite_flag("SQLITE_DUAL_WRITE"))
        self.assertTrue(sqlite_flag("SQLITE_READ"))
        self.assertTrue(sqlite_flag("SQLITE_PIPELINE_READ"))
        self.assertTrue(sqlite_flag("SQLITE_WRITE_PRIMARY"))
        self.assertTrue(sqlite_flag("SQLITE_DASHBOARD_WRITE"))
        self.assertTrue(sqlite_flag("SQLITE_EXPORT_JOBS_CSV"))
        self.assertFalse(sqlite_flag("SQLITE_QUERY_STATE_READ"))
        self.assertFalse(sqlite_flag("SQLITE_EXPORT_HISTORICAL_CSV"))
        self.assertFalse(sqlite_flag("SQLITE_EXPORT_DESCRIPTIONS_CSV"))
        self.assertFalse(sqlite_flag("SQLITE_EXPORT_CRM_CSV"))

    def test_sqlite_enabled_zero_disables_master(self) -> None:
        from db.config import sqlite_flag
        from db.read.engine import (
            dashboard_read_enabled,
            dashboard_write_enabled,
            pipeline_read_enabled,
            read_access_enabled,
        )
        from db.reset_sqlite import sqlite_reset_enabled
        from db.services import dual_write as dual_write_module
        from db.write.engine import write_primary_enabled

        os.environ["SQLITE_ENABLED"] = "0"

        self.assertFalse(sqlite_flag("SQLITE_ENABLED"))
        self.assertFalse(read_access_enabled())
        self.assertFalse(pipeline_read_enabled())
        self.assertFalse(dashboard_read_enabled())
        self.assertFalse(dashboard_write_enabled())
        self.assertFalse(write_primary_enabled())
        self.assertFalse(sqlite_reset_enabled())
        self.assertFalse(dual_write_module._dual_write_enabled())

    def test_runtime_gates_default_on(self) -> None:
        from db.read.engine import (
            dashboard_read_enabled,
            dashboard_write_enabled,
            pipeline_read_enabled,
        )
        from db.reset_sqlite import sqlite_reset_enabled
        from db.write.engine import (
            export_crm_csv_enabled,
            export_descriptions_csv_enabled,
            export_historical_csv_enabled,
            write_primary_enabled,
        )

        self.assertTrue(pipeline_read_enabled())
        self.assertTrue(write_primary_enabled())
        self.assertTrue(dashboard_read_enabled())
        self.assertTrue(dashboard_write_enabled())
        self.assertTrue(sqlite_reset_enabled())
        self.assertFalse(export_historical_csv_enabled())
        self.assertFalse(export_descriptions_csv_enabled())
        self.assertFalse(export_crm_csv_enabled())


if __name__ == "__main__":
    unittest.main()
