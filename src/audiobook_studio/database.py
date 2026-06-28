"""Database utilities for Audiobook Studio.

Provides a SQLAlchemy 2.0 engine and a scoped session factory.
PostgreSQL 通过 DATABASE_URL 环境变量配置，开发环境默认 SQLite。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# ── Base class for all ORM models (SQLAlchemy 2.0 style) ──


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


# Resolve database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'audiobook.db'}",
)

# check_same_thread required for SQLite in multithreaded FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    ),
    echo=False,
    pool_pre_ping=True,  # 连接池健康检查
)

# Session factory (2.0 style)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db():
    """Generator function that yields database sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not exist (MVP convenience; production uses Alembic)."""

    # Import all models to register with Base
    from .models import (  # noqa: F401
        audio_segment,
        book,
        chapter,
        character,
        emotion_snapshot,
        feedback_record,
        paragraph,
        processing_run,
        quality,
        routing,
        tts_edit,
    )

    Base.metadata.create_all(bind=engine)
