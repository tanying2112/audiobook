"""Application settings for Audiobook Studio."""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# 把 .env 注入 os.environ: pydantic Settings 只读 .env 到 Settings 对象,
# 但 LiteLLM / provider key pool 直接读 os.environ (如 OPENAI_API_KEY、
# KILO_API_KEY)。若不加载, 除 fcc (硬编码 extra_headers) 外所有 provider
# 都会因 "Missing credentials" 失败。此处一次性加载, uvicorn/celery/脚本均受益。
from pathlib import Path as _Path

try:
    from dotenv import load_dotenv as _load_dotenv

    _env_file = _Path(".env")
    if _env_file.exists():
        _load_dotenv(_env_file)
except ImportError:  # pragma: no cover - dotenv 可选
    pass

from ..database import _get_async_database_url


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
        default=["localhost", "127.0.0.1", "testserver"],
        alias="ALLOWED_HOSTS",
    )

    # Cloud Studio / multi-tenant workspace (S3.6)
    CLOUD_STUDIO_MODE: bool = Field(default=False, alias="CLOUD_STUDIO_MODE")
    WORKSPACE_QUOTA_PROJECTS: int = Field(default=10, alias="WORKSPACE_QUOTA_PROJECTS")
    WORKSPACE_QUOTA_USERS: int = Field(default=50, alias="WORKSPACE_QUOTA_USERS")
    MULTI_REGION_ENABLED: bool = Field(default=False, alias="MULTI_REGION_ENABLED")
    REGION_ID: str = Field(default="local", alias="REGION_ID")

    # API rate limiting / quota (S3.6)
    RATE_LIMIT_ENABLED: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    # Redis dependency mode: required | optional
    # "required" = fail startup if Redis unreachable (production)
    # "optional" = warn and continue with in-memory cache (development / potato mode)
    REDIS_REQUIRED: bool = Field(default=True, alias="REDIS_REQUIRED")
    RATE_LIMIT_PER_USER_PER_MINUTE: int = Field(default=60, alias="RATE_LIMIT_PER_USER_PER_MINUTE")
    RATE_LIMIT_BURST: int = Field(default=10, alias="RATE_LIMIT_BURST")

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

    # 自我迭代 Harness 是否以 mock_mode 空跑 (C-01)。
    # 默认 true 保持既有行为; CI/生产设 false 走真实 LLM 进化链路。
    SELF_ITERATION_MOCK: bool = Field(default=True, alias="SELF_ITERATION_MOCK")

    # Mock mode for LLM/TTS (used by pipeline stages)
    MOCK_LLM: bool = Field(default=False, alias="MOCK_LLM")
    MOCK_TTS: bool = Field(default=False, alias="MOCK_TTS")

    # Audio processing
    CROSSFADE_MS: int = Field(default=50, alias="CROSSFADE_MS")
    AUDIO_SEMANTIC_CACHE_ENABLED: bool = Field(default=False, alias="AUDIO_SEMANTIC_CACHE_ENABLED")

    # DNSMOS model paths
    DNSMOS_MODEL_URL: Optional[str] = Field(default=None, alias="DNSMOS_MODEL_URL")
    DNSMOS_MODEL_PATH: str = Field(default="dnsmos.onnx", alias="DNSMOS_MODEL_PATH")

    # Tesseract OCR
    TESSERACT_CMD: Optional[str] = Field(default=None, alias="TESSERACT_CMD")

    # Model cache directory
    AUDIOBOOK_STUDIO_MODEL_CACHE: str = Field(default="~/.cache/audiobook_studio/models", alias="AUDIOBOOK_STUDIO_MODEL_CACHE")

    # ffmpeg concurrency control
    FFMPEG_CONCURRENCY: int = Field(default=0, alias="FFMPEG_CONCURRENCY")  # 0=auto(cpu_count-1)

    # Logging
    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")
    LOG_FORMAT: str = Field(default="json", alias="LOG_FORMAT")

    # Auth registration mode: open | invite | approval
    # Secure default is "invite" - anonymous self-registration is disabled unless a
    # valid invite code (REGISTRATION_INVITE_CODES) is supplied or an admin bootstraps.
    AUTH_REGISTRATION_MODE: str = Field(default="invite", alias="AUTH_REGISTRATION_MODE")
    # Comma-separated invite codes accepted when AUTH_REGISTRATION_MODE=invite.
    REGISTRATION_INVITE_CODES: str = Field(default="", alias="REGISTRATION_INVITE_CODES")

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
        except Exception as e:
            raise RuntimeError(
                f"Refusing to start: JWT_SECRET_KEY is not valid URL-safe base64. "
                f"Generate a secure key with: python scripts/generate_secrets.py --format env"
            ) from e

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

    # =========================================================================
    # BP-003: Runtime dependency validation (DB, Redis, Models, LLM Keys)
    # =========================================================================
    async def validate_runtime_dependencies(self, timeout: float = 5.0) -> None:
        """Validate critical runtime dependencies at startup (BP-003).

        Checks:
        1. Database connectivity (async SELECT 1)
        2. Redis connectivity (async ping)
        3. Model file existence (Kokoro model path if configured)
        4. LLM API key format validation (basic format checks for configured keys)

        Args:
            timeout: Timeout in seconds for each connectivity check.

        Raises:
            RuntimeError: If any critical dependency check fails with clear error message.
        """
        logger = logging.getLogger("audiobook_studio.startup")

        # Offline / "potato mode": skip non-critical external dependency checks
        # (Redis, local model files, LLM key formats). Database is always verified.
        # Set SKIP_RUNTIME_DEPS=1 for zero-config startup without Redis.
        skip_external = os.environ.get("SKIP_RUNTIME_DEPS", "").lower() in ("1", "true", "yes", "on")

        # 1. Database connectivity (async)
        try:
            async_engine = create_async_engine(
                _get_async_database_url(),
                pool_pre_ping=True,
            )
            async with asyncio.timeout(timeout):
                async with async_engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            await async_engine.dispose()
            logger.info("Database connectivity: OK")
        except Exception as e:
            logger.critical(f"DATABASE_URL connect failed: {e}")
            raise RuntimeError(
                f"DATABASE_URL connect failed: {e}. "
                f"Check DATABASE_URL={self.DATABASE_URL}"
            ) from e

        # 2. Redis connectivity (async ping)
        try:
            import redis.asyncio as aioredis

            async with asyncio.timeout(timeout):
                r = aioredis.from_url(self.REDIS_URL)
                await r.ping()
                await r.aclose()
            logger.info("Redis connectivity: OK")
        except Exception as e:
            if skip_external or not self.REDIS_REQUIRED:
                # Offline / potato mode / optional Redis: degrade gracefully.
                logger.warning(
                    f"Redis ping failed (continuing without Redis): {e}"
                )
            else:
                logger.critical(f"Redis ping failed: {e}")
                raise RuntimeError(f"Redis ping failed: {e}. Check REDIS_URL={self.REDIS_URL}") from e

        # 3. Kokoro model file existence (if local TTS enabled)
        if self.ENABLE_LOCAL_TTS and self.KOKORO_MODEL_PATH:
            model_path = Path(self.KOKORO_MODEL_PATH)
            if not model_path.exists():
                if skip_external:
                    logger.warning(
                        f"KOKORO_MODEL_PATH not found (SKIP_RUNTIME_DEPS set, continuing): "
                        f"{self.KOKORO_MODEL_PATH}"
                    )
                else:
                    logger.critical(f"KOKORO_MODEL_PATH not found: {self.KOKORO_MODEL_PATH}")
                    raise RuntimeError(
                        f"KOKORO_MODEL_PATH not found: {self.KOKORO_MODEL_PATH}. "
                        f"Download models or set ENABLE_LOCAL_TTS=false to use Edge-TTS fallback."
                    )
            else:
                logger.info(f"Kokoro model file found: {self.KOKORO_MODEL_PATH}")

        # 4. LLM API key format validation (basic format checks for configured keys)
        # 4. LLM API key format validation (basic format checks for configured keys)
        if skip_external:
            logger.warning("Skipping LLM API key format validation (SKIP_RUNTIME_DEPS set).")
        else:
            self._validate_llm_api_keys()

    def _validate_llm_api_keys(self) -> None:
        """Validate format of configured LLM API keys.

        Performs basic format validation on known LLM provider API keys.
        Does not validate actual API access (too slow for startup).
        """
        import re

        logger = logging.getLogger("audiobook_studio.startup")

        # Provider -> (key attr name, regex pattern, description)
        validators = {
            "GROQ_API_KEY": (
                self.GROQ_API_KEY,
                r"^gsk_[A-Za-z0-9]{52}$",
                "GROQ (format: gsk_<52-chars>)",
            ),
            "OPENAI_API_KEY": (
                self.OPENAI_API_KEY,
                r"^sk-[A-Za-z0-9]{48,}$",
                "OPENAI (format: sk-<48+ chars>)",
            ),
            "ANTHROPIC_API_KEY": (
                self.ANTHROPIC_API_KEY,
                r"^sk-ant-api03-[A-Za-z0-9\-_]{95,}$",
                "ANTHROPIC (format: sk-ant-api03-<95+ chars>)",
            ),
            "GEMINI_API_KEY": (
                self.GEMINI_API_KEY,
                r"^[A-Za-z0-9\-_]{39}$",
                "GEMINI (format: 39 chars alphanumeric/underscore/hyphen)",
            ),
            "DEEPSEEK_API_KEY": (
                self.DEEPSEEK_API_KEY,
                r"^sk-[A-Za-z0-9]{32,}$",
                "DEEPSEEK (format: sk-<32+ chars>)",
            ),
            "OPENROUTER_API_KEY": (
                self.OPENROUTER_API_KEY,
                r"^sk-or-v1-[A-Za-z0-9]{64,}$",
                "OPENROUTER (format: sk-or-v1-<64+ chars>)",
            ),
            "NVIDIA_API_KEY": (
                self.NVIDIA_API_KEY,
                r"^nvapi-[A-Za-z0-9\-_]{60,}$",
                "NVIDIA (format: nvapi-<60+ chars>)",
            ),
        }

        for attr_name, (key_value, pattern, description) in validators.items():
            if key_value is not None and key_value.strip():
                if not re.match(pattern, key_value.strip()):
                    logger.critical(f"Invalid {attr_name} format: expected {description}")
                    raise RuntimeError(
                        f"Invalid {attr_name} format (expected {description}). "
                        f"Check {attr_name} in environment/.env — invalid format will cause API failures."
                    )
                logger.info(f"{attr_name} format: OK")
