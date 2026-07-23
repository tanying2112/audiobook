"""FastAPI dependencies for the Audiobook Studio API.

Provides both sync and async ``get_db`` dependencies that yield a SQLAlchemy session
and ensure it is closed after the request.
"""

from typing import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..database import AsyncSessionLocal, SessionLocal, get_async_session


def get_db() -> Generator[Session, None, None]:
    """Yield a synchronous database session for a request (legacy).

    The session is closed automatically when the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for a request (recommended).

    Uses the async SQLAlchemy 2.0 session factory for better concurrency.
    """
    async for session in get_async_session():
        yield session
