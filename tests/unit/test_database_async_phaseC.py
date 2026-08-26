"""Phase C structural tests for database_async.py (async engine/session + Base helpers)."""

import asyncio
import os

import pytest
from sqlalchemy import Column, Integer, String

import src.audiobook_studio.database_async as da
from src.audiobook_studio.database_async import Base


class _Sample(Base):
    __tablename__ = "phasec_sample"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    score = Column(Integer, default=0)


def _reset(monkeypatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(da, "_engine", None)
    monkeypatch.setattr(da, "_async_session_factory", None)


# ── Base helpers ──────────────────────────────────────────────────────────────


def test_base_to_dict_and_repr():
    obj = _Sample(id=1, name="hello")
    d = obj.to_dict()
    assert d["id"] == 1
    assert d["name"] == "hello"
    assert "_Sample" in repr(obj)


def test_base_to_dict_datetime_iso():
    from datetime import datetime

    from sqlalchemy import DateTime

    class _Timed(Base):
        __tablename__ = "phasec_timed"
        id = Column(Integer, primary_key=True)
        created = Column(DateTime)

    obj = _Timed(id=7, created=datetime(2024, 1, 2, 3, 4, 5))
    d = obj.to_dict()
    assert d["created"] == "2024-01-02T03:04:05"


# ── Engine URL conversion ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,expected_driver",
    [
        ("sqlite:///data/x.db", "sqlite+aiosqlite"),
        ("sqlite+aiosqlite:///data/x.db", "sqlite+aiosqlite"),
        ("postgresql://u@h/db", "postgresql+asyncpg"),
        ("postgresql+psycopg2://u@h/db", "postgresql+asyncpg"),
    ],
)
def test_engine_url_conversion(monkeypatch, url, expected_driver):
    _reset(monkeypatch, url)
    eng = da.get_async_engine()
    assert eng.url.drivername == expected_driver


# ── Session factory / session ──────────────────────────────────────────────────


def test_get_async_session_factory_and_create(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'a.db'}")
    factory = da.get_async_session_factory()
    assert factory is not None
    session = da.create_async_session()
    try:
        assert session is not None
    finally:
        asyncio.run(session.close())


@pytest.mark.asyncio
async def test_async_session_local_commit(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'b.db'}")
    async with da.AsyncSessionLocal() as session:
        assert session is not None


@pytest.mark.asyncio
async def test_async_session_local_rollback(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'c.db'}")

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        async with da.AsyncSessionLocal() as session:
            assert session is not None
            raise _Boom()


@pytest.mark.asyncio
async def test_get_async_session_yields(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'d.db'}")

    seen = []

    async def run():
        async for session in da.get_async_session():
            seen.append(session)
            return

    await run()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_get_async_session_rollback_on_sql_error(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'e.db'}")

    from sqlalchemy.exc import SQLAlchemyError

    with pytest.raises(SQLAlchemyError):
        async for session in da.get_async_session():
            # Force a SQLAlchemy-level error to trigger rollback branch
            await session.execute("SELECT * FROM nonexistent_table_xyz")
            return


@pytest.mark.asyncio
async def test_init_and_drop_async_db(monkeypatch, tmp_path):
    _reset(monkeypatch, f"sqlite+aiosqlite:///{tmp_path/'f.db'}")
    await da.init_async_db()
    await da.drop_async_db()
