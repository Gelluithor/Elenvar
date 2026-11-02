"""Databázová vrstva (SQLite přes SQLAlchemy async)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Ukládá čas jako naivní UTC, vrací vždy časově zónově uvědomělý UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime is not allowed – use UTC with tzinfo")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


settings.data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = settings.data_dir / "elenvar.db"

engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    connect_args={"timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# Sloupce přidané po verzi 1.0 – create_all nemění existující tabulky.
_ADDED_COLUMNS = {
    "nvrs": {"stream_mode": "VARCHAR(16) NOT NULL DEFAULT 'auto'"},
    "cameras": {
        "custom_name": "VARCHAR(128) NOT NULL DEFAULT ''",
        "rotation": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _add_missing_columns(conn) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def init_db() -> None:
    from . import models  # noqa: F401  (registrace modelů)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
