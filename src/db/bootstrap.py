"""Database bootstrap: ensure file exists and apply Alembic migrations."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

import paths
from db.config import database_url, sqlite_flags_summary
from db.engine import get_engine
from db.models import Base

# Skip redundant Alembic upgrade runs within a process (e.g. Streamlit reruns).
_BOOTSTRAP_DONE: set[tuple[str, str]] = set()


def _reset_bootstrap_guard() -> None:
    """Clear process-level bootstrap cache (tests only)."""
    _BOOTSTRAP_DONE.clear()


def repo_root() -> Path:
    return paths.REPO_ROOT


def alembic_ini_path() -> Path:
    return repo_root() / "alembic.ini"


def alembic_config() -> Config:
    config = Config(str(alembic_ini_path()))
    config.set_main_option("script_location", str(repo_root() / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url())
    return config


def ensure_database_file() -> Path:
    db_path = paths.jobs_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        db_path.touch()
    return db_path


def upgrade_schema(*, revision: str = "head") -> str:
    """Apply migrations up to revision (default: head). Returns resolved revision id."""
    ensure_database_file()
    config = alembic_config()
    command.upgrade(config, revision)
    script = ScriptDirectory.from_config(config)
    with get_engine().connect() as connection:
        context = MigrationContext.configure(connection)
        current = context.get_current_revision()
    if current:
        return current
    return script.get_current_head() or revision


def ensure_database_ready(*, revision: str = "head") -> Path:
    """Create DB file if needed and migrate schema."""
    db_path = ensure_database_file()
    bootstrap_key = (str(db_path.resolve()), revision)
    if bootstrap_key in _BOOTSTRAP_DONE:
        return db_path
    upgrade_schema(revision=revision)
    _BOOTSTRAP_DONE.add(bootstrap_key)
    return db_path


def print_database_status() -> None:
    db_path = paths.jobs_db()
    print("\n" + "=" * 60)
    print("SQLite foundation status")
    print("=" * 60)
    print(f"Database path: {db_path}")
    print(f"Database exists: {db_path.is_file()}")
    if db_path.is_file():
        print(f"Database size (bytes): {db_path.stat().st_size}")
    print(f"Database URL: {database_url()}")
    print("\nFeature flags (scaffolding only — pipeline not wired):")
    for key, value in sqlite_flags_summary().items():
        print(f"  {key}={int(value)}")
    config = alembic_config()
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    current = None
    if db_path.is_file():
        with get_engine().connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()
    print(f"\nAlembic head revision: {head}")
    print(f"Alembic current revision: {current or '(none)'}")
    if db_path.is_file():
        inspector = inspect(get_engine())
        tables = sorted(inspector.get_table_names())
        print(f"\nTables ({len(tables)}):")
        for name in tables:
            print(f"  - {name}")
        if set(tables) >= set(Base.metadata.tables.keys()):
            print("\nMVP schema tables: present")
        else:
            missing = sorted(set(Base.metadata.tables.keys()) - set(tables))
            print(f"\nMVP schema tables missing: {', '.join(missing)}")
    print("=" * 60 + "\n")
