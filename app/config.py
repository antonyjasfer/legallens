"""Centralized application configuration with environment variable validation."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


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

    # --- Google Cloud Platform Services ---
    google_cloud_project: str = Field(default="papertrail-ai-2026", description="GCP Project ID")
    google_cloud_location: str = Field(default="us-central1", description="GCP Region / Location")
    gcs_bucket: str = Field(default="", description="Google Cloud Storage bucket for legal documents")
    firestore_database: str = Field(default="(default)", description="Firestore database name")
    document_ai_enabled: bool = Field(default=False, description="Enable Document AI layout parser")
    document_ai_processor_id: str = Field(default="", description="Document AI processor resource or ID")
    document_retention_days: int = Field(default=7, description="Document retention days before auto-cleanup")

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

    @property
    def gcs_configured(self) -> bool:
        return bool(self.gcs_bucket)

    @property
    def firestore_configured(self) -> bool:
        return bool(self.google_cloud_project and self.firestore_database)

    @property
    def document_ai_configured(self) -> bool:
        return bool(self.document_ai_enabled and self.document_ai_processor_id and self.google_cloud_project)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Prioritize .env file values over stale OS-level environment variables."""
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
