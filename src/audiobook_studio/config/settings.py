"""Application settings for Audiobook Studio."""

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Audiobook Studio"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = Field(default=False, alias="DEBUG")
    ENVIRONMENT: str = Field(default="development", alias="ENVIRONMENT")

    # API
    API_V1_PREFIX: str = "/api"
    OPENAPI_URL: str = "/openapi.json"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"

    # CORS
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ],
        alias="CORS_ORIGINS",
    )
    # P0-3: 生产环境 CORS 方法白名单（覆盖 allow_methods=["*"] 的默认不安全行为）
    CORS_ALLOW_METHODS: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
        alias="CORS_ALLOW_METHODS",
    )
    CORS_ALLOW_HEADERS: List[str] = Field(
        default=["*"],
        alias="CORS_ALLOW_HEADERS",
    )

    # Database
    DATABASE_URL: str = Field(default="sqlite:///./data/audiobook.db", alias="DATABASE_URL")

    # JWT Authentication
    JWT_SECRET_KEY: str = Field(default="your-super-secret-key-change-in-production", alias="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = Field(default="HS256", alias="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # Password hashing
    BCRYPT_ROUNDS: int = Field(default=12, alias="BCRYPT_ROUNDS")

    # LLM Providers
    GROQ_API_KEY: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    OPENAI_API_KEY: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    GEMINI_API_KEY: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    DEEPSEEK_API_KEY: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    NVIDIA_API_KEY: Optional[str] = Field(default=None, alias="NVIDIA_API_KEY")

    # TTS
    EDGE_TTS_VOICE: str = Field(default="zh-CN-XiaoxiaoNeural", alias="EDGE_TTS_VOICE")
    KOKORO_MODEL_PATH: Optional[str] = Field(default=None, alias="KOKORO_MODEL_PATH")
    ENABLE_LOCAL_TTS: bool = Field(default=True, alias="ENABLE_LOCAL_TTS")

    # Storage
    STORAGE_PATH: str = Field(default="./storage", alias="STORAGE_PATH")
    MAX_UPLOAD_SIZE: int = Field(default=100 * 1024 * 1024, alias="MAX_UPLOAD_SIZE")  # 100MB

    # Logging
    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")
    LOG_FORMAT: str = Field(default="json", alias="LOG_FORMAT")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    OTEL_CONSOLE_EXPORTER: bool = Field(default=False, alias="OTEL_CONSOLE_EXPORTER")
    PROMETHEUS_PORT: int = Field(default=9090, alias="PROMETHEUS_PORT")

    # Langfuse
    LANGFUSE_PUBLIC_KEY: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: Optional[str] = Field(default=None, alias="LANGFUSE_HOST")

    # =========================================================================
    # P0-2: JWT 密钥启动校验
    # =========================================================================
    def validate_jwt_secret(self) -> None:
        """Validate JWT secret is not the default placeholder in production.

        Raises:
            RuntimeError: If JWT_SECRET_KEY is the default placeholder in production environment.
        """
        default_placeholders = {
            "your-super-secret-key-change-in-production",
            "test-secret-key-for-ci-only",
            "your-secret-key-change-in-production",  # legacy .env.example value
        }
        if self.ENVIRONMENT == "production" and self.JWT_SECRET_KEY in default_placeholders:
            raise RuntimeError(
                f"Refusing to start: JWT_SECRET_KEY is a default placeholder "
                f"({self.JWT_SECRET_KEY[:20]}...). "
                f"Set a strong random secret via JWT_SECRET_KEY environment variable "
                f"before running in production. See docs/AUDIT_REPORT_v3.md P0-2."
            )

    def validate_cors_security(self) -> None:
        """Validate CORS configuration for production security.

        Warns if allow_origins=["*"] with allow_credentials=True which is a dangerous combination.
        """
        if self.ENVIRONMENT == "production":
            if "*" in self.CORS_ORIGINS and self.CORS_ALLOW_METHODS == ["*"]:
                import warnings

                warnings.warn(
                    "CORS misconfiguration: allow_origins=['*'] with allow_methods=['*'] "
                    "and allow_credentials=True is dangerous. "
                    "Set CORS_ORIGINS to explicit origins and CORS_ALLOW_METHODS to explicit methods.",
                    UserWarning,
                    stacklevel=2,
                )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        # Validate security settings on first load
        _settings.validate_jwt_secret()
        _settings.validate_cors_security()
    return _settings
