"""Unified Configuration Manager for Audiobook Studio.

Consolidates configuration from multiple sources:
- Environment variables (.env file)
- YAML configuration files (config/*.yaml)
- docker-compose files (for container orchestration)
- pyproject.toml (for tooling metadata)

Provides a single source of truth for all configuration.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator

from .settings import Settings


class UnifiedConfig:
    """Unified configuration manager with priority-based merging.

    Priority order (highest to lowest):
    1. Environment variables (explicit, override everything)
    2. .env file (loaded by pydantic Settings)
    3. YAML config files (config/*.yaml)
    4. docker-compose.yml (for container-specific settings)
    5. pyproject.toml (for tooling defaults)
    6. Built-in defaults
    """

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self._settings: Optional[Settings] = None
        self._yaml_cache: Dict[str, Dict[str, Any]] = {}
        self._docker_compose_cache: Dict[str, Any] = {}
        self._pyproject_cache: Dict[str, Any] = {}

    @property
    def settings(self) -> Settings:
        """Get or create the pydantic Settings instance (from .env)."""
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    # =========================================================================
    # YAML Configuration Loading
    # =========================================================================

    def load_yaml_config(self, config_name: str) -> Dict[str, Any]:
        """Load a YAML configuration file with caching.

        Args:
            config_name: Name of config file (e.g., "pipeline", "quality_thresholds")

        Returns:
            Parsed configuration dict, or empty dict if not found.
        """
        if config_name in self._yaml_cache:
            return self._yaml_cache[config_name]

        config_path = self.project_root / "config" / f"{config_name}.yaml"
        if not config_path.exists():
            config_path = self.project_root / "config" / f"{config_name}.yml"

        if not config_path.exists():
            logger = self._get_logger()
            logger.warning(f"Config file not found: {config_name}.yaml")
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                result = data if isinstance(data, dict) else {}
                self._yaml_cache[config_name] = result
                return result
        except yaml.YAMLError as e:
            logger = self._get_logger()
            logger.error(f"Failed to parse YAML {config_name}: {e}")
            return {}
        except Exception as e:
            logger = self._get_logger()
            logger.error(f"Error reading {config_name}: {e}")
            return {}

    def load_all_yaml_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load all YAML configs in config/ directory."""
        configs = {}
        config_dir = self.project_root / "config"
        if config_dir.exists():
            for config_file in config_dir.glob("*.yaml"):
                name = config_file.stem
                if not name.endswith(".bak") and name != "agent_sop":
                    configs[name] = self.load_yaml_config(name)
            for config_file in config_dir.glob("*.yml"):
                name = config_file.stem
                if name not in configs:
                    configs[name] = self.load_yaml_config(name)
        return configs

    # =========================================================================
    # Docker Compose Configuration Loading
    # =========================================================================

    def load_docker_compose(self, filename: str = "docker-compose.yml") -> Dict[str, Any]:
        """Load docker-compose configuration with caching.

        Args:
            filename: Docker compose file name

        Returns:
            Parsed docker-compose dict, or empty dict if not found.
        """
        cache_key = filename
        if cache_key in self._docker_compose_cache:
            return self._docker_compose_cache[cache_key]

        compose_path = self.project_root / filename
        if not compose_path.exists():
            return {}

        try:
            with open(compose_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                result = data if isinstance(data, dict) else {}
                self._docker_compose_cache[cache_key] = result
                return result
        except Exception as e:
            logger = self._get_logger()
            logger.error(f"Error reading {filename}: {e}")
            return {}

    def load_all_docker_compose(self) -> Dict[str, Dict[str, Any]]:
        """Load all docker-compose files."""
        configs = {}
        for compose_file in self.project_root.glob("docker-compose*.yml"):
            name = compose_file.stem.replace("docker-compose.", "")
            if name == "docker-compose":
                name = "default"
            configs[name] = self.load_docker_compose(compose_file.name)
        return configs

    def get_service_env(self, service_name: str, compose_name: str = "default") -> Dict[str, str]:
        """Extract environment variables for a specific service from docker-compose.

        Args:
            service_name: Name of the service (e.g., "api", "worker", "redis")
            compose_name: Which docker-compose file to use

        Returns:
            Dict of environment variable names to values (with ${VAR} interpolation).
        """
        compose = self.load_docker_compose(
            f"docker-compose.{compose_name}.yml" if compose_name != "default" else "docker-compose.yml"
        )
        services = compose.get("services", {})
        service = services.get(service_name, {})
        env_vars = service.get("environment", {})

        # Convert list format to dict if needed
        if isinstance(env_vars, list):
            env_dict = {}
            for item in env_vars:
                if "=" in item:
                    key, value = item.split("=", 1)
                    env_dict[key] = self._interpolate_env(value)
            return env_dict

        # Already a dict, interpolate values
        return {k: self._interpolate_env(v) for k, v in env_vars.items()}

    def _interpolate_env(self, value: str) -> str:
        """Interpolate ${VAR} and $VAR references with environment values."""
        # ${VAR} format
        def replace_var(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        value = re.sub(r"\$\{([^}]+)\}", replace_var, value)

        # $VAR format (but not $$ which is escaped $)
        def replace_simple(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        value = re.sub(r"(?<!\$)\$([A-Z_][A-Z0-9_]*)", replace_simple, value)
        return value

    # =========================================================================
    # pyproject.toml Configuration Loading
    # =========================================================================

    def load_pyproject(self) -> Dict[str, Any]:
        """Load pyproject.toml configuration with caching."""
        if self._pyproject_cache:
            return self._pyproject_cache

        pyproject_path = self.project_root / "pyproject.toml"
        if not pyproject_path.exists():
            return {}

        try:
            import tomllib
        except ImportError:
            # Python < 3.11
            try:
                import tomli as tomllib
            except ImportError:
                logger = self._get_logger()
                logger.warning("tomllib/tomli not available, cannot parse pyproject.toml")
                return {}

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                self._pyproject_cache = data if isinstance(data, dict) else {}
                return self._pyproject_cache
        except Exception as e:
            logger = self._get_logger()
            logger.error(f"Error reading pyproject.toml: {e}")
            return {}

    def get_tool_config(self, tool: str, *keys: str) -> Any:
        """Get nested configuration from [tool.*] section in pyproject.toml.

        Args:
            tool: Tool name (e.g., "pytest", "ruff", "mypy")
            *keys: Nested keys to traverse

        Returns:
            Configuration value or None if not found.
        """
        pyproject = self.load_pyproject()
        tool_section = pyproject.get("tool", {}).get(tool, {})

        current = tool_section
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None

        return current

    # =========================================================================
    # Unified Configuration Access
    # =========================================================================

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value with priority-based resolution.

        Priority:
        1. Environment variable (uppercase, with underscores)
        2. Settings (from .env via pydantic)
        3. YAML configs (flattened)
        4. docker-compose service env (if service context available)
        5. Default

        Args:
            key: Configuration key (e.g., "database.url", "tts.kokoro.model_path")
            default: Default value if not found

        Returns:
            Configuration value or default.
        """
        # 1. Check environment variable (highest priority)
        env_key = key.upper().replace(".", "_").replace("-", "_")
        if env_key in os.environ:
            return os.environ[env_key]

        # 2. Check Settings (from .env)
        if hasattr(self.settings, env_key):
            return getattr(self.settings, env_key)

        # 3. Check YAML configs (flattened)
        yaml_value = self._get_from_yaml(key)
        if yaml_value is not None:
            return yaml_value

        return default

    def _get_from_yaml(self, key: str) -> Any:
        """Get value from YAML configs by flattened key path."""
        # Try common config sections
        for config_name in ["pipeline", "quality_thresholds", "tts_providers", "hardware_profile"]:
            config = self.load_yaml_config(config_name)
            value = self._get_nested(config, key.split("."))
            if value is not None:
                return value

        return None

    def _get_nested(self, data: Dict[str, Any], keys: List[str]) -> Any:
        """Get nested value from dict by key list."""
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section as dict.

        Args:
            section: Section name (e.g., "database", "tts", "llm", "storage")

        Returns:
            Merged configuration dict for that section.
        """
        result = {}

        # From Settings
        settings_dict = self.settings.model_dump()
        for k, v in settings_dict.items():
            if k.lower().startswith(section.lower()):
                result[k] = v

        # From YAML configs
        yaml_configs = self.load_all_yaml_configs()
        for config_name, config in yaml_configs.items():
            if config_name.startswith(section):
                result[config_name] = config

        # From docker-compose (service env)
        docker_configs = self.load_all_docker_compose()
        for compose_name, compose in docker_configs.items():
            services = compose.get("services", {})
            for svc_name, svc_config in services.items():
                if section.lower() in svc_name.lower():
                    env = svc_config.get("environment", {})
                    if isinstance(env, list):
                        for item in env:
                            if "=" in item:
                                k, v = item.split("=", 1)
                                result[f"{svc_name}.{k}"] = v
                    else:
                        for k, v in env.items():
                            result[f"{svc_name}.{k}"] = v

        return result

    def get_database_config(self) -> Dict[str, Any]:
        """Get consolidated database configuration."""
        return {
            "url": self.settings.DATABASE_URL,
            "sync_url": self._get_async_to_sync_url(self.settings.DATABASE_URL),
            "echo": self.settings.get("SQL_ECHO", "false").lower() == "true",
            "pool_pre_ping": True,
            "pool_recycle": 3600,
        }

    def _get_async_to_sync_url(self, url: str) -> str:
        """Convert async database URL to sync version."""
        if url.startswith("sqlite+aiosqlite:///"):
            return url.replace("sqlite+aiosqlite:///", "sqlite:///")
        elif url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite+aiosqlite://", "sqlite://")
        elif url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://")
        elif url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql+psycopg2://", "postgresql://")
        return url

    def get_redis_config(self) -> Dict[str, Any]:
        """Get consolidated Redis configuration."""
        return {
            "url": self.settings.REDIS_URL,
            "max_connections": self.settings.REDIS_MAX_CONNECTIONS,
            "pool_size": self.settings.REDIS_POOL_SIZE,
            "socket_keepalive": self.settings.REDIS_SOCKET_KEEPALIVE,
            "retry_on_timeout": self.settings.REDIS_RETRY_ON_TIMEOUT,
        }

    def get_llm_config(self) -> Dict[str, Any]:
        """Get consolidated LLM configuration."""
        config = {
            "providers": {},
            "mock_mode": self.settings.MOCK_LLM if hasattr(self.settings, "MOCK_LLM") else False,
        }

        # Provider API keys from settings
        providers = [
            "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
            "NVIDIA_API_KEY"
        ]
        for provider in providers:
            key = getattr(self.settings, provider, None)
            if key:
                config["providers"][provider.replace("_API_KEY", "").lower()] = key

        # From llm_providers.yaml
        llm_yaml = self.load_yaml_config("llm_providers")
        if llm_yaml:
            config.update(llm_yaml)

        return config

    def get_tts_config(self) -> Dict[str, Any]:
        """Get consolidated TTS configuration."""
        config = {
            "enable_local": self.settings.ENABLE_LOCAL_TTS,
            "kokoro_model_path": self.settings.KOKORO_MODEL_PATH,
            "edge_voice": self.settings.EDGE_TTS_VOICE,
        }

        # From tts_providers.yaml
        tts_yaml = self.load_yaml_config("tts_providers")
        if tts_yaml:
            config.update(tts_yaml)

        # From voice_mapping.yaml
        voice_yaml = self.load_yaml_config("voice_mapping")
        if voice_yaml:
            config["voice_mapping"] = voice_yaml

        return config

    def get_pipeline_config(self) -> Dict[str, Any]:
        """Get consolidated pipeline configuration."""
        config = self.load_yaml_config("pipeline")
        return config

    def get_hardware_profile(self) -> Dict[str, Any]:
        """Get hardware profile configuration."""
        return self.load_yaml_config("hardware_profile")

    # =========================================================================
    # Validation and Utilities
    # =========================================================================

    def validate_all(self) -> List[str]:
        """Validate all configuration and return list of issues."""
        issues = []

        # Validate settings
        try:
            self.settings.validate_jwt_secret()
        except RuntimeError as e:
            issues.append(f"JWT: {e}")

        try:
            self.settings.validate_cors_security()
        except RuntimeError as e:
            issues.append(f"CORS: {e}")

        # Check required files
        required_files = [
            self.project_root / "config" / "pipeline.yaml",
            self.project_root / "config" / "quality_thresholds.yaml",
        ]
        for f in required_files:
            if not f.exists():
                issues.append(f"Missing required config: {f.relative_to(self.project_root)}")

        return issues

    def dump_all(self) -> Dict[str, Any]:
        """Dump all configuration for debugging (with sensitive values masked)."""
        result = {
            "settings": self._mask_sensitive(self.settings.model_dump()),
            "yaml_configs": self._mask_sensitive(self.load_all_yaml_configs()),
            "docker_compose": self._mask_sensitive(self.load_all_docker_compose()),
            "pyproject": self._mask_sensitive(self.load_pyproject()),
        }
        return result

    def _mask_sensitive(self, data: Any) -> Any:
        """Recursively mask sensitive values in configuration."""
        if isinstance(data, dict):
            masked = {}
            for k, v in data.items():
                key_lower = k.lower()
                if any(sensitive in key_lower for sensitive in [
                    "key", "secret", "password", "token", "api_key"
                ]):
                    if isinstance(v, str) and v:
                        masked[k] = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
                    else:
                        masked[k] = v
                else:
                    masked[k] = self._mask_sensitive(v)
            return masked
        elif isinstance(data, list):
            return [self._mask_sensitive(item) for item in data]
        else:
            return data

    def _get_logger(self):
        import logging
        return logging.getLogger("audiobook_studio.config.unified")


# Global instance
_unified_config: Optional[UnifiedConfig] = None


def get_unified_config() -> UnifiedConfig:
    """Get the global UnifiedConfig instance."""
    global _unified_config
    if _unified_config is None:
        _unified_config = UnifiedConfig()
    return _unified_config


def reset_unified_config() -> None:
    """Reset the global UnifiedConfig instance (for testing)."""
    global _unified_config
    _unified_config = None


# Convenience functions
def get_config(key: str, default: Any = None) -> Any:
    """Get a configuration value from the unified config."""
    return get_unified_config().get(key, default)


def get_database_config() -> Dict[str, Any]:
    """Get database configuration."""
    return get_unified_config().get_database_config()


def get_redis_config() -> Dict[str, Any]:
    """Get Redis configuration."""
    return get_unified_config().get_redis_config()


def get_llm_config() -> Dict[str, Any]:
    """Get LLM configuration."""
    return get_unified_config().get_llm_config()


def get_tts_config() -> Dict[str, Any]:
    """Get TTS configuration."""
    return get_unified_config().get_tts_config()


def get_pipeline_config() -> Dict[str, Any]:
    """Get pipeline configuration."""
    return get_unified_config().get_pipeline_config()


def get_hardware_profile() -> Dict[str, Any]:
    """Get hardware profile configuration."""
    return get_unified_config().get_hardware_profile()


def validate_config() -> List[str]:
    """Validate all configuration."""
    return get_unified_config().validate_all()


def dump_config() -> Dict[str, Any]:
    """Dump all configuration for debugging."""
    return get_unified_config().dump_all()
