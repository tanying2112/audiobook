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

    # Security - Trusted Hosts (for TrustedHostMiddleware)
    ALLOWED_HOSTS: List[str] = Field(
        default=["localhost", "127.0.0.1"],
        alias="ALLOWED_HOSTS",
    )

    # Database
    DATABASE_URL: str = Field(default="sqlite:///./data/audiobook.db", alias="DATABASE_URL")

    # JWT Authentication
    JWT_SECRET_KEY: str = Field(alias="JWT_SECRET_KEY")
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

    # Redis (connectivity + pool)
    REDIS_URL: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    REDIS_MAX_CONNECTIONS: int = Field(default=50, alias="REDIS_MAX_CONNECTIONS")
    REDIS_POOL_SIZE: int = Field(default=20, alias="REDIS_POOL_SIZE")
    REDIS_SOCKET_KEEPALIVE: int = Field(default=30, alias="REDIS_SOCKET_KEEPALIVE")
    REDIS_RETRY_ON_TIMEOUT: bool = Field(default=True, alias="REDIS_RETRY_ON_TIMEOUT")

    # Health check
    HEALTH_CHECK_TIMEOUT: float = Field(default=5.0, alias="HEALTH_CHECK_TIMEOUT")

    # ffmpeg concurrency control
    FFMPEG_CONCURRENCY: int = Field(default=0, alias="FFMPEG_CONCURRENCY")  # 0=auto(cpu_count-1)

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
    # P0-2: JWT 密钥启动校验（无条件强制执行，满足 SEC-001）
    # =========================================================================
    def validate_jwt_secret(self) -> None:
        """Validate JWT secret is not a default placeholder and has sufficient entropy.

        Raises:
            RuntimeError: If JWT_SECRET_KEY is a default placeholder or has < 256-bit entropy.
        """
        # Check for default placeholders
        default_placeholders = {
            "your-super-secret-key-change-in-production",
            "test-secret-key-for-ci-only",
            "your-secret-key-change-in-production",  # legacy .env.example value
        }
        if self.JWT_SECRET_KEY in default_placeholders:
            raise RuntimeError(
                f"Refusing to start: JWT_SECRET_KEY is a default placeholder "
                f"({self.JWT_SECRET_KEY[:20]}...). "
                f"Generate a secure key with: python scripts/generate_secrets.py --format env"
            )

        # Check minimum entropy: 256 bits = 32 bytes = at least 43 URL-safe base64 chars (without padding)
        # Base64 URL-safe alphabet: A-Z, a-z, 0-9, -, _ (64 chars = 6 bits/char)
        # 32 bytes -> 43-44 chars (without '=' padding)
        min_chars = 43
        if len(self.JWT_SECRET_KEY) < min_chars:
            raise RuntimeError(
                f"Refusing to start: JWT_SECRET_KEY is too short "
                f"({len(self.JWT_SECRET_KEY)} chars, need ≥{min_chars} for 256-bit entropy). "
                f"Generate a secure key with: python scripts/generate_secrets.py --format env"
            )

        # Verify it's valid URL-safe base64 (no disallowed chars)
        import base64
        try:
            # Add padding if needed for validation
            padded = self.JWT_SECRET_KEY + "=" * ((4 - len(self.JWT_SECRET_KEY) % 4) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            if len(decoded) < 32:
                raise ValueError("Decoded length < 32 bytes")
        except Exception:
            raise RuntimeError(
                f"Refusing to start: JWT_SECRET_KEY is not valid URL-safe base64. "
                f"Generate a secure key with: python scripts/generate_secrets.py --format env"
            )

    def validate_cors_security(self) -> None:
        """Validate CORS configuration for production security.

        Raises RuntimeError in production if:
        - "*" is in CORS_ORIGINS (wildcard origin)
        - CORS_ALLOW_METHODS == ["*"] (wildcard methods)
        - allow_credentials=True with wildcard origins
        """
        if self.ENVIRONMENT == "production":
            issues = []
            if "*" in self.CORS_ORIGINS:
                issues.append("allow_origins contains wildcard '*'")
            if self.CORS_ALLOW_METHODS == ["*"]:
                issues.append("allow_methods is wildcard ['*']")
            if issues:
                raise RuntimeError(
                    f"Refusing to start in production: CORS misconfiguration - {', '.join(issues)}. "
                    f"Set CORS_ORIGINS to explicit origins and CORS_ALLOW_METHODS to explicit methods. "
                    f"See docs/AUDIT_REPORT_v3.md P0-3."
                )
