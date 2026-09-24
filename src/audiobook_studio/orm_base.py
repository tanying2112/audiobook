"""SQLAlchemy 2.0 DeclarativeBase for Audiobook Studio ORM models.

This module provides the shared Base class to avoid circular imports
between database.py and models/.
"""

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 DeclarativeBase with common helpers."""

    # Common columns for all models
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

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


__all__ = ["Base"]
