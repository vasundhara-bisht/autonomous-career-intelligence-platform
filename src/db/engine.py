"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.config import database_url


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    engine = create_engine(
        database_url(),
        future=True,
        connect_args={"check_same_thread": False},
    )
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def get_session() -> Session:
    return get_session_factory()()
