"""FastAPI dependency injection providers."""

from app.config import Settings, get_settings


def get_app_settings() -> Settings:
    """Dependency for injecting application settings into routes."""
    return get_settings()
