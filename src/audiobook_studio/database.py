"""Database utilities for Audiobook Studio.

Provides both sync and async SQLAlchemy 2.0 engines and session factories.
PostgreSQL 通过 DATABASE_URL 环境变量配置，开发环境默认 SQLite。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# ── Base class for all ORM models (SQLAlchemy 2.0 style) ───


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 DeclarativeBase with common helpers."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize model instance to a plain dict (JSON-safe)."""
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


# ── Sync Engine & Session Factory (legacy, for backward compatibility) ───

# Resolve database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'audiobook.db'}",
)

# check_same_thread required for SQLite in multithreaded FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args=({"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}),
    echo=False,
    pool_pre_ping=True,  # 连接池健康检查
)

# Session factory (2.0 style)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db():
    """Generator function that yields database sessions (sync)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Async Engine & Session Factory (new, recommended) ───

_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_async_database_url() -> str:
    """Convert sync DATABASE_URL to async version."""
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    return url


def get_async_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            _get_async_database_url(),
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _async_engine


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


async def get_async_session() -> AsyncSession:
    """Async generator function that yields database sessions (for FastAPI dependency)."""
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


def init_db() -> None:
    """Create all tables if they do not exist (sync version, MVP convenience)."""
    # Import all models to register with Base (lazy import to avoid circular deps)
    from .models import (  # noqa: F401
        audio_segment,
        book,
        chapter,
        character,
        collaboration,
        emotion_snapshot,
        feedback_record,
        paragraph,
        processing_run,
        quality,
        routing,
        tts_edit,
    )

    Base.metadata.create_all(bind=engine)


# ── Export all ───

__all__ = [
    # Sync (legacy)
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "DATABASE_URL",
    # Async (new, recommended)
    "get_async_engine",
    "get_async_session_factory",
    "init_async_db",
    "drop_async_db",
    "get_async_session",
    "AsyncSessionLocal",
    "create_async_session",
]