"""Database utilities for Audiobook Studio.

Provides both sync and async SQLAlchemy 2.0 engines and session factories.
PostgreSQL 通过 DATABASE_URL 环境变量配置，开发环境默认 SQLite。
"""

import os
import random
from sqlalchemy.exc import SQLAlchemyError
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, TYPE_CHECKING
from contextlib import asynccontextmanager

import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from .orm_base import Base

logger = logging.getLogger(__name__)


def _get_sync_database_url() -> str:
    """Convert async DATABASE_URL to sync version for sync engine and alembic."""
    url = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'audiobook.db'}",
    )
    # Convert async drivers to sync
    if url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite+aiosqlite:///", "sqlite:///")
    elif url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    elif url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://")
    return url


# Resolve database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'audiobook.db'}",
)

# Sync engine URL (converts sqlite+aiosqlite:// to sqlite:// for sync engine)
SYNC_DATABASE_URL = _get_sync_database_url()

# check_same_thread required for SQLite in multithreaded FastAPI
engine = create_engine(
    SYNC_DATABASE_URL,
    connect_args=({"check_same_thread": False} if SYNC_DATABASE_URL.startswith("sqlite") else {}),
    echo=False,
    pool_pre_ping=True,  # 连接池健康检查
)

# Session factory (2.0 style)
if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    SyncSessionFactory = sessionmaker[Session]
else:
    SyncSessionFactory = sessionmaker

SessionLocal: SyncSessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db() -> AsyncGenerator[Any, None]:
    """Generator function that yields database sessions (sync)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Async Engine & Session Factory (new, recommended) ───

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
    from sqlalchemy.orm import Session, sessionmaker

    AsyncSessionFactory = async_sessionmaker[AsyncSession]
else:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
    from sqlalchemy.orm import Session, sessionmaker

    AsyncSessionFactory = async_sessionmaker

_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[AsyncSessionFactory] = None


def _get_async_database_url() -> str:
    """Convert sync DATABASE_URL to async version."""
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    elif url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    return url


def get_sync_engine_url() -> str:
    """Get the sync database URL for sync engine creation."""
    return DATABASE_URL


def _install_slow_query_logger(engine: "AsyncEngine") -> None:
    """Install a threshold-based slow-query logger on the sync engine.

    S2.6 — configurable slow-query alerting. The threshold is read from the
    ``SLOW_QUERY_MS`` env var (default 1000ms). Set ``SLOW_QUERY_MS=0`` to
    disable. In local dev this surfaces N+1 / missing-index hotspots without
    failing requests.
    """
    import time

    threshold_ms = float(os.getenv("SLOW_QUERY_MS", "1000"))
    if threshold_ms <= 0:
        return

    from sqlalchemy import event

    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(statement, parameters, context, cursor, *args):  # noqa: ANN001
        # Some SQLAlchemy versions pass context as string, not ExecutionContext
        if hasattr(context, "__dict__"):
            context._slow_q_start = time.perf_counter()  # type: ignore[attr-defined]

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(statement, parameters, context, cursor, *args):  # noqa: ANN001
        # Some SQLAlchemy versions pass context as string, not ExecutionContext
        if not hasattr(context, "__dict__"):
            return
        start = getattr(context, "_slow_q_start", None)
        if start is None:
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms >= threshold_ms:
            logger.warning(
                "[SLOW-QUERY] %.1fms (threshold=%.0fms) — %s",
                elapsed_ms,
                threshold_ms,
                " ".join(str(statement).split())[:300],
            )


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
        _install_slow_query_logger(_async_engine)
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


# ── Read Replica Configuration & Routing (P2-5) ───

class DatabaseConfig:
    """Database configuration with read replica support.
    
    Attributes:
        primary_url: Primary database URL for writes
        replica_urls: List of read replica URLs for SELECT queries
        enable_routing: Whether to enable read/write routing
    """
    
    def __init__(
        self,
        primary_url: str,
        replica_urls: Optional[List[str]] = None,
        enable_routing: bool = True,
    ):
        self.primary_url = primary_url
        self.replica_urls = replica_urls or []
        self.enable_routing = enable_routing and len(self.replica_urls) > 0


class ReadReplicaSelector:
    """Round-robin selector for read replicas.
    
    Provides fair distribution of read queries across available replicas.
    """
    
    def __init__(self, replicas: List[str]):
        self.replicas = replicas
        self._index = 0
    
    def get_replica(self) -> str:
        """Get next replica in round-robin fashion."""
        if not self.replicas:
            raise ValueError("No replicas configured")
        replica = self.replicas[self._index]
        self._index = (self._index + 1) % len(self.replicas)
        return replica
    
    def get_random_replica(self) -> str:
        """Get a random replica (alternative strategy)."""
        if not self.replicas:
            raise ValueError("No replicas configured")
        return random.choice(self.replicas)


class RoutedEngine:
    """Manages primary and replica engines with query routing.
    
    Routes SELECT queries to replicas, all other queries to primary.
    """
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._primary_engine: Optional[AsyncEngine] = None
        self._replica_engines: List[AsyncEngine] = []
        self._selector = ReadReplicaSelector(config.replica_urls) if config.replica_urls else None
    
    async def initialize(self) -> None:
        """Initialize all engines."""
        # Primary engine
        self._primary_engine = create_async_engine(
            self._to_async_url(self.config.primary_url),
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        _install_slow_query_logger(self._primary_engine)
        
        # Replica engines
        for replica_url in self.config.replica_urls:
            engine = create_async_engine(
                self._to_async_url(replica_url),
                echo=os.getenv("SQL_ECHO", "false").lower() == "true",
                pool_pre_ping=True,
                pool_recycle=3600,
            )
            _install_slow_query_logger(engine)
            self._replica_engines.append(engine)
    
    @staticmethod
    def _to_async_url(url: str) -> str:
        """Convert sync URL to async version."""
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///")
        elif url.startswith("sqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://")
        elif url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://")
        elif url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        return url
    
    @property
    def primary_engine(self) -> AsyncEngine:
        """Get primary engine for writes."""
        if self._primary_engine is None:
            raise RuntimeError("RoutedEngine not initialized. Call initialize() first.")
        return self._primary_engine
    
    def get_replica_engine(self) -> AsyncEngine:
        """Get a replica engine for reads (round-robin)."""
        if not self.config.enable_routing or not self._replica_engines:
            return self.primary_engine
        idx = self._selector._index % len(self._replica_engines)
        return self._replica_engines[idx]
    
    async def close(self) -> None:
        """Close all engines."""
        if self._primary_engine:
            await self._primary_engine.dispose()
        for engine in self._replica_engines:
            await engine.dispose()
        self._primary_engine = None
        self._replica_engines = []


class RoutedSession(AsyncSession):
    """AsyncSession that routes queries based on operation type.
    
    SELECT -> replica (if available)
    INSERT/UPDATE/DELETE -> primary
    """
    
    def __init__(self, routed_engine: RoutedEngine, **kwargs):
        kwargs.pop("bind", None)
        super().__init__(bind=routed_engine.primary_engine, **kwargs)
        self._routed_engine = routed_engine
        self._use_replica = False
    
    def _should_use_replica(self) -> bool:
        """Determine if current query should use replica."""
        return self._use_replica and self._routed_engine.config.enable_routing
    
    async def execute(self, statement, *args, **kwargs):
        """Execute statement with automatic routing."""
        from sqlalchemy import Select
        
        # Determine if this is a read-only query
        is_select = isinstance(statement, Select)
        
        # Check for FOR UPDATE / FOR SHARE clauses which require primary
        if is_select:
            # Check if statement has locking clauses
            if hasattr(statement, '_for_update_arg') and statement._for_update_arg:
                is_select = False
        
        # Route to appropriate engine
        if is_select and self._should_use_replica():
            # Use replica for reads
            replica_engine = self._routed_engine.get_replica_engine()
            return await super().execute(statement, *args, **kwargs, execution_options={"engine": replica_engine})
        else:
            # Use primary for writes and locking reads
            return await super().execute(statement, *args, **kwargs)
    
    def enable_replica(self) -> "RoutedSession":
        """Enable replica routing for subsequent queries in this session."""
        self._use_replica = True
        return self
    
    def disable_replica(self) -> "RoutedSession":
        """Disable replica routing (force primary)."""
        self._use_replica = False
        return self


@asynccontextmanager
async def get_routed_session(config: DatabaseConfig) -> AsyncGenerator[RoutedSession, None]:
    """Create a routed session with automatic routing.
    
    Usage:
        async with get_routed_session(config) as session:
            # SELECT queries go to replica
            result = await session.execute(select(Chapter).where(...))
            # INSERT/UPDATE go to primary
            await session.add(obj)
    """
    if not hasattr(get_routed_session, "_routed_engine"):
        get_routed_session._routed_engine = RoutedEngine(config)
        await get_routed_session._routed_engine.initialize()
    
    session = RoutedSession(get_routed_session._routed_engine, expire_on_commit=False, autoflush=False)
    session.enable_replica()
    
    try:
        yield session
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise
    finally:
        await session.close()


# Global routed engine instance (lazy initialization)
_routed_engine: Optional[RoutedEngine] = None
_routed_session_factory: Optional[async_sessionmaker[RoutedSession]] = None


def get_routed_engine() -> RoutedEngine:
    """Get or create the global routed engine."""
    global _routed_engine
    if _routed_engine is None:
        # Build config from environment
        primary_url = os.getenv("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'audiobook.db'}")
        replica_urls_str = os.getenv("DATABASE_REPLICA_URLS", "")
        replica_urls = [u.strip() for u in replica_urls_str.split(",") if u.strip()] if replica_urls_str else []
        
        config = DatabaseConfig(
            primary_url=primary_url,
            replica_urls=replica_urls,
            enable_routing=os.getenv("ENABLE_READ_REPLICA", "false").lower() == "true",
        )
        _routed_engine = RoutedEngine(config)
        # Note: initialize() must be called before first use
    return _routed_engine


async def init_routed_engine() -> RoutedEngine:
    """Initialize the routed engine (call on startup)."""
    engine = get_routed_engine()
    await engine.initialize()
    return engine


async def close_routed_engine() -> None:
    """Close the routed engine (call on shutdown)."""
    global _routed_engine
    if _routed_engine:
        await _routed_engine.close()
        _routed_engine = None


def get_routed_session_factory() -> async_sessionmaker[RoutedSession]:
    """Get or create the routed session factory."""
    global _routed_session_factory
    if _routed_session_factory is None:
        engine = get_routed_engine()
        _routed_session_factory = async_sessionmaker(
            class_=RoutedSession,
            expire_on_commit=False,
            autoflush=False,
        )
        # Bind will be set per-session in RoutedSession.__init__
    return _routed_session_factory


async def get_routed_session() -> AsyncGenerator[RoutedSession, None]:
    """Get a routed session (FastAPI dependency).
    
    Usage:
        @app.get("/chapters")
        async def get_chapters(session: RoutedSession = Depends(get_routed_session)):
            ...
    """
    routed_engine = get_routed_engine()
    factory = get_routed_session_factory()
    session = factory(routed_engine=routed_engine)
    # Bind to primary engine initially
    if routed_engine._primary_engine:
        session.bind = routed_engine.primary_engine
    session.enable_replica()
    
    try:
        yield session
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async generator function that yields database sessions (for FastAPI dependency).
    
    Uses routed session if read replicas are configured, otherwise standard session.
    """
    # Check if routing is enabled
    if os.getenv("ENABLE_READ_REPLICA", "false").lower() == "true" and os.getenv("DATABASE_REPLICA_URLS"):
        async for session in get_routed_session():
            yield session
    else:
        factory = get_async_session_factory()
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except SQLAlchemyError:
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
    """Create all tables if they do not exist (sync version, MVP convenience).

    Note: Models must be imported before calling this function to register
    with Base.metadata. Caller is responsible for importing all models.
    """
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
    "get_sync_engine_url",
    # Async (new, recommended)
    "get_async_engine",
    "get_async_session_factory",
    "init_async_db",
    "drop_async_db",
    "get_async_session",
    "AsyncSessionLocal",
    "create_async_session",
    # Read Replica (P2-5)
    "DatabaseConfig",
    "ReadReplicaSelector",
    "RoutedEngine",
    "RoutedSession",
    "get_routed_engine",
    "init_routed_engine",
    "close_routed_engine",
    "get_routed_session_factory",
    "get_routed_session",
]
