"""Tests for SQLite-first validation modes (production vs csv-mirror-sync)."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for entry in (str(_REPO_ROOT), str(_SRC), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _load_validate_sqlite_parity():
    spec = importlib.util.spec_from_file_location(
        "validate_sqlite_parity",
        _SCRIPTS / "validate_sqlite_parity.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validate_dual_write_parity():
    spec = importlib.util.spec_from_file_location(
        "validate_dual_write_parity",
        _SCRIPTS / "validate_dual_write_parity.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidationModeParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        os.environ["AI_JOB_AGENT_DATA_DIR"] = str(self._data)
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._data / "test.db")
        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["SQLITE_DUAL_WRITE"] = "1"
        os.environ["SQLITE_WRITE_PRIMARY"] = "1"
        os.environ["SQLITE_EXPORT_HISTORICAL_CSV"] = "0"
        os.environ["SQLITE_EXPORT_CRM_CSV"] = "0"
        _clear_db_caches()

        self.historical_path = self._data / "historical_jobs.csv"
        self.jobs_path = self._data / "jobs.csv"
        self.crm_path = self._data / "recruiter_crm.csv"

    def tearDown(self) -> None:
        _clear_db_caches()
        self._tmpdir.cleanup()
        for key in (
            "AI_JOB_AGENT_DATA_DIR",
            "AI_JOB_AGENT_DB_PATH",
            "SQLITE_ENABLED",
            "SQLITE_DUAL_WRITE",
            "SQLITE_WRITE_PRIMARY",
            "SQLITE_EXPORT_HISTORICAL_CSV",
            "SQLITE_EXPORT_CRM_CSV",
        ):
            os.environ.pop(key, None)

    def _patch_paths(self):
        return mock.patch.multiple(
            "paths",
            historical_jobs_csv=lambda: self.historical_path,
            jobs_csv=lambda: self.jobs_path,
            job_descriptions_csv=lambda: self._data / "job_descriptions.csv",
            recruiter_crm_csv=lambda: self.crm_path,
            linkedin_query_state_json=lambda: self._data / ".linkedin_query_state.json",
        )

    def _seed_db_job(self, key_v2: str = "v2:test:validation:1") -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import (
            AcquisitionRun,
            AiEvaluation,
            Job,
            JobObservation,
        )

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            run = AcquisitionRun(started_at=now, completed_at=now, status="completed")
            session.add(run)
            session.flush()
            job = Job(
                job_key="legacy-key",
                job_key_v2=key_v2,
                title="PM",
                company="Co",
            )
            session.add(job)
            session.flush()
            session.add(
                JobObservation(
                    job_id=job.id,
                    run_id=run.id,
                    source="greenhouse",
                    observed_at=now,
                )
            )
            session.add(
                AiEvaluation(
                    job_id=job.id,
                    run_id=run.id,
                    ai_status="scored",
                    ai_score=7.0,
                    model="test",
                    evaluated_at=now,
                )
            )
            session.commit()

    def test_subset_check_fails_csv_mirror_sync_with_empty_historical(self) -> None:
        from db.services.parity_checks import (
            check_jobs_csv_subset_of_historical,
            read_csv,
        )

        key = "v2:test:validation:1"
        pd.DataFrame(
            [{"JOB_KEY_V2": key, "ai_status": "scored", "ai_score": "7.0"}]
        ).to_csv(self.jobs_path, index=False)
        self.historical_path.write_text("", encoding="utf-8")

        jobs = read_csv(self.jobs_path)
        historical = read_csv(self.historical_path)
        result = check_jobs_csv_subset_of_historical(jobs, historical)
        self.assertFalse(result.ok())
        self.assertTrue(any("not in historical_jobs.csv" in f for f in result.failures))

    def test_production_report_ok_with_empty_historical_and_populated_db(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.parity_checks import (
            check_acquisition_runtime_parity,
            check_operational_cohort_parity,
            check_orphan_recruiter_links,
            check_production_cumulative_health,
            check_production_db_health,
            merge_sections,
            read_csv,
        )

        key = "v2:test:validation:1"
        self._seed_db_job(key)
        pd.DataFrame(
            [{"JOB_KEY_V2": key, "ai_status": "scored", "ai_score": "7.0"}]
        ).to_csv(self.jobs_path, index=False)
        self.historical_path.write_text("", encoding="utf-8")

        with self._patch_paths():
            ensure_database_ready()
            jobs = read_csv(self.jobs_path)
            historical = read_csv(self.historical_path)
            with get_session() as session:
                report = merge_sections(
                    check_production_db_health(session, jobs),
                    check_operational_cohort_parity(session, jobs),
                    check_acquisition_runtime_parity(session, jobs),
                    check_orphan_recruiter_links(session),
                    check_production_cumulative_health(session, historical),
                )
        self.assertTrue(report.ok(), report.failures)

    def _write_historical_with_stale_acme(self, valid_key: str = "v2:test:validation:1") -> None:
        pd.DataFrame(
            [
                {
                    "JOB_KEY": "pm::acme",
                    "JOB_KEY_V2": "v2:greenhouse:acme:exp1",
                    "title": "PM",
                    "company": "Acme",
                    "ai_status": "scored",
                    "ai_score": "8.0",
                },
                {
                    "JOB_KEY": "legacy-key",
                    "JOB_KEY_V2": valid_key,
                    "title": "PM",
                    "company": "Co",
                    "ai_status": "scored",
                    "ai_score": "7.0",
                },
            ]
        ).to_csv(self.historical_path, index=False)

    def test_production_warns_stale_historical_keys_when_export_off(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.parity_checks import check_production_cumulative_health, read_csv

        key = "v2:test:validation:1"
        self._seed_db_job(key)
        self._write_historical_with_stale_acme(key)

        with self._patch_paths():
            ensure_database_ready()
            historical = read_csv(self.historical_path)
            with get_session() as session:
                result = check_production_cumulative_health(session, historical)

        self.assertTrue(result.ok(), result.failures)
        self.assertTrue(
            any("historical JOB_KEY_V2" in w and "acme:exp1" in w for w in result.warnings),
            result.warnings,
        )
        self.assertTrue(
            any("SQLITE_EXPORT_HISTORICAL_CSV=0" in w for w in result.warnings),
            result.warnings,
        )

    def test_production_fails_stale_historical_keys_when_export_on(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.parity_checks import check_production_cumulative_health, read_csv

        key = "v2:test:validation:1"
        self._seed_db_job(key)
        self._write_historical_with_stale_acme(key)

        with mock.patch.dict(os.environ, {"SQLITE_EXPORT_HISTORICAL_CSV": "1"}, clear=False):
            _clear_db_caches()
            with self._patch_paths():
                ensure_database_ready()
                historical = read_csv(self.historical_path)
                with get_session() as session:
                    result = check_production_cumulative_health(session, historical)

        self.assertFalse(result.ok())
        self.assertTrue(
            any("historical JOB_KEY_V2" in f and "acme:exp1" in f for f in result.failures),
            result.failures,
        )

    def test_production_fails_on_orphan_recruiter_link(self) -> None:
        from sqlalchemy import text

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.parity_checks import check_orphan_recruiter_links

        self._seed_db_job()
        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.execute(text("PRAGMA foreign_keys=OFF"))
            session.execute(
                text(
                    "INSERT INTO recruiter_job_links (recruiter_id, job_id, linked_at) "
                    "VALUES (99999, 99999, :linked_at)"
                ),
                {"linked_at": now},
            )
            session.execute(text("PRAGMA foreign_keys=ON"))
            session.commit()
            result = check_orphan_recruiter_links(session)
        self.assertFalse(result.ok())
        self.assertTrue(any("orphan recruiter_job_links" in f for f in result.failures))

    def test_query_state_non_strict_emits_warnings_not_failures(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import QueryCooldownState
        from db.services.parity_checks import check_query_state_parity

        state_path = self._data / ".linkedin_query_state.json"
        state_path.write_text(
            '{"last_run_by_query_id": {"q1": 100.0}, "domain_rotation_index": 0}',
            encoding="utf-8",
        )
        ensure_database_ready()
        with get_session() as session:
            session.add(
                QueryCooldownState(
                    query_id="q2",
                    last_run_at=200.0,
                    domain_rotation_index=1,
                )
            )
            session.commit()
            with mock.patch(
                "db.services.parity_checks.paths.linkedin_query_state_json",
                return_value=state_path,
            ):
                loose = check_query_state_parity(session, strict=False)
                strict = check_query_state_parity(session, strict=True)
        self.assertFalse(strict.ok())
        self.assertTrue(loose.ok())
        self.assertTrue(loose.warnings)

    def test_dual_write_wrapper_prints_deprecation(self) -> None:
        dual = _load_validate_dual_write_parity()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with mock.patch.object(
                dual,
                "_load_sqlite_parity_module",
                return_value=mock.MagicMock(run_csv_mirror_sync_mode=lambda **_: 0),
            ):
                with mock.patch.object(sys, "argv", ["validate_dual_write_parity.py"]):
                    dual.main()
        self.assertIn("DEPRECATED", stderr.getvalue())
        self.assertIn("production", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
