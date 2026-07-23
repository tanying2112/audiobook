"""Async Database utilities for Audiobook Studio.

Provides a SQLAlchemy 2.0 async engine and an async scoped session factory.
PostgreSQL 通过 DATABASE_URL 环境变量配置，开发环境默认 SQLite。
"""

import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# ── Base class for all ORM models (SQLAlchemy 2.0 style) ──


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 DeclarativeBase with common helpers."""

    def to_dict(self) -> dict:
        """Serialize model instance to a plain dict (JSON-safe)."""
        from datetime import datetime

        result = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            result[col.name] = val
        return result

    def __repr__(self) -> str:
        pk = [c.name for c in self.__table__.primary_key.columns]
        pk_vals = {k: getattr(self, k) for k in pk}
        return f"<{self.__class__.__name__}({pk_vals})>"


# ── Engine & Session Factory ──

_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_async_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/audiobook.db")

        # Convert sync SQLite URL to async
        if database_url.startswith("sqlite:///"):
            database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
        elif database_url.startswith("sqlite://"):
            database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg2://"):
            database_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

        _engine = create_async_engine(
            database_url,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


async def init_async_db() -> None:
    """Initialize database tables (async version)."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_async_db() -> None:
    """Drop all database tables (async version, DESTRUCTIVE!)."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session."""
    factory = get_async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class AsyncSessionLocal:
    """Async context manager for database sessions (legacy compatibility)."""

    def __init__(self):
        self._session: Optional[AsyncSession] = None

    async def __aenter__(self) -> AsyncSession:
        factory = get_async_session_factory()
        self._session = factory()
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            if exc_type:
                await self._session.rollback()
            else:
                await self._session.commit()
            await self._session.close()


def create_async_session() -> AsyncSession:
    """Create a new async session (for non-FastAPI contexts)."""
    factory = get_async_session_factory()
    return factory()


# ── Compatibility aliases for sync database module ──

# These allow gradual migration without breaking existing code
__all__ = [
    "Base",
    "get_async_engine",
    "get_async_session_factory",
    "init_async_db",
    "drop_async_db",
    "get_async_session",
    "AsyncSessionLocal",
    "create_async_session",
]
