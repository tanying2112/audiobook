"""FastAPI dependencies for the Audiobook Studio API.

Provides a ``get_db`` dependency that yields a SQLAlchemy session and ensures it
is closed after the request.
"""

from typing import Generator

from sqlalchemy.orm import Session

from ..database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for a request.

    The session is closed automatically when the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
