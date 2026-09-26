"""Centralized application configuration with environment variable validation."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Core ---
    app_name: str = "LegalLens"
    app_version: str = "1.0.0"
    app_env: str = Field(default="development", description="development | staging | production")

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = Field(default=8080, description="Server port; Cloud Run sets PORT env var")

    # --- Upload ---
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    upload_dir: Path = Field(default=Path("/tmp/legallens_uploads"))
    allowed_mime_types: list[str] = ["application/pdf"]

    # --- Google Gemini ---
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(default="gemini-3.8-flash", description="Gemini model name")

    # --- Optional GCP ---
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    document_ai_processor_id: str = ""

    # --- Security ---
    cors_origins: list[str] = Field(default=["*"])
    max_request_body_mb: int = 12
    api_timeout_seconds: int = 120

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
