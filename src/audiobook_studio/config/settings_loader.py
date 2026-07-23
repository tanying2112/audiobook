"""Settings loader for Audiobook Studio.

This module provides lazy loading of the Settings singleton to avoid
circular import issues. The Settings class is defined in settings.py,
but this module handles the singleton instance creation and validation.
"""

from typing import Optional

from src.audiobook_studio.config.settings import Settings

# Global settings instance - lazily initialized
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance.

    This function is safe to call from anywhere in the codebase.
    It ensures settings are validated only once on first access.
    """
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
        # Validate security settings on first load
        _settings.validate_jwt_secret()
        _settings.validate_cors_security()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance (useful for testing)."""
    global _settings
    _settings = None


# Export the loader functions
__all__ = ["get_settings", "reset_settings"]