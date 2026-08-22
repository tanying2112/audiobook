"""Provider and Model configuration models for dynamic supplier management."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..orm_base import Base


def utc_now() -> datetime:
    """Return current UTC time as timezone-naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


if TYPE_CHECKING:
    from .user import User


class Provider(Base):
    """动态供应商模型 - 可在前端UI中实时添加/编辑。

    与 .env / yaml 配置不同，此模型存储在数据库中，
    允许用户无需重启服务即可添加新的 LLM 提供商、模型和 API key。
    """

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Provider configuration
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "openai", "anthropic", "nvidia_nemotron", "fcc_gateway"
    api_base: Mapped[str] = mapped_column(Text, nullable=True)  # e.g., "https://api.openai.com/v1"
    api_key: Mapped[str] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="bearer")  # "bearer", "api_key", "none"

    # Model configuration
    default_model: Mapped[str] = mapped_column(String(100), nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=True, default=4000)
    temperature: Mapped[float] = mapped_column(Float, nullable=True, default=0.1)

    # Status and metadata
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)  # Lower = higher priority
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)  # Username or "system"

    # Relationships
    models: Mapped[List["Model"]] = relationship("Model", back_populates="provider", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Provider(id={self.id}, name={self.name}, priority={self.sort_priority})>"


class Model(Base):
    """动态模型配置模型 - 归属于一个 Provider。

    存储模型名称、版本、提示词模板等配置信息，
    允许用户在不改动代码的情况下扩展支持的模型。
    """

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False)

    # Model details
    model_id: Mapped[str] = mapped_column(String(100), nullable=True)  # e.g., "gpt-4o", "claude-3-opus"
    version: Mapped[str] = mapped_column(String(50), nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, nullable=True, default=128000)

    # Configuration
    instructions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Status
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="models")

    def __repr__(self) -> str:
        return f"<Model(id={self.id}, name={self.name}, provider={self.provider.name})>"
