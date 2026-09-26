"""Google Cloud Storage service for secure, private legal document storage.

Enforces:
- Local PDF validation (size <= 10MB, application/pdf, %PDF magic bytes, sanitized name)
- Server-controlled object paths: legal-documents/<session_id>/<document_id>.pdf
- Strictly PRIVATE storage — no public URLs
- Metadata tracking (document_id, original_filename, sha256, uploaded_at, retention_days)
- Clean temporary file lifecycle and deletion
- Safe local scratch fallback when GCS is unconfigured in development
"""

from __future__ import annotations

import datetime
import io
import logging
from pathlib import Path
from typing import Any

from google.cloud import storage

from app.config import get_settings
from app.core.errors import (
    FileTooLargeError,
    FileValidationError,
    GCSStorageError,
    InvalidFileTypeError,
)
from app.core.security import compute_file_hash, sanitize_filename, validate_pdf_magic

logger = logging.getLogger("legallens.gcs")


class GCSService:
    """Manages secure, private storage of uploaded legal documents in Google Cloud Storage."""

    _instance: GCSService | None = None

    def __init__(self) -> None:
        self._client: storage.Client | None = None
        self._bucket_name: str = ""

    @classmethod
    def get_instance(cls) -> GCSService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_configured(self) -> bool:
        if self._client is not None:
            return True
        settings = get_settings()
        return bool(settings.gcs_bucket and settings.google_cloud_project)

    def _get_client(self) -> storage.Client:
        if self._client is None:
            settings = get_settings()
            try:
                self._client = storage.Client(project=settings.google_cloud_project)
            except Exception as exc:
                logger.warning("Could not initialize GCS client: %s", exc)
                raise GCSStorageError(f"Cloud Storage client initialization failed: {type(exc).__name__}") from exc
        return self._client

    async def health_check(self) -> dict[str, Any]:
        """Verify Cloud Storage connectivity and bucket access without leaking secrets."""
        settings = get_settings()
        if not self.is_configured:
            return {
                "configured": False,
                "reachable": False,
                "bucket": "not_configured",
                "message": "GCS_BUCKET not set; running in local ephemeral storage mode",
            }

        try:
            client = self._get_client()
            bucket = client.bucket(settings.gcs_bucket)
            exists = bucket.exists()
            return {
                "configured": True,
                "reachable": exists,
                "bucket": settings.gcs_bucket,
            }
        except Exception as exc:
            logger.warning("GCS health check probe failed: %s", type(exc).__name__)
            return {
                "configured": True,
                "reachable": False,
                "bucket": settings.gcs_bucket,
                "error": type(exc).__name__,
            }

    def validate_pdf_content(self, content: bytes, original_filename: str) -> None:
        """Enforce strict local validation rules before any cloud storage."""
        settings = get_settings()

        # 1. Size check
        if len(content) > settings.max_upload_bytes:
            raise FileTooLargeError(
                f"File size ({len(content) / (1024 * 1024):.1f} MB) exceeds maximum allowed {settings.max_upload_mb} MB"
            )

        # 2. Non-empty check
        if not content:
            raise FileValidationError("Uploaded file is empty.")

        # 3. Magic bytes check
        if not validate_pdf_magic(content):
            raise InvalidFileTypeError("File content does not match PDF format (%PDF signature missing).")

    def upload_document(
        self,
        content: bytes,
        original_filename: str,
        session_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        """Upload a validated legal document to Google Cloud Storage.

        Generates server-controlled object ID: legal-documents/<session_id>/<document_id>.pdf
        """
        self.validate_pdf_content(content, original_filename)

        safe_name = sanitize_filename(original_filename)
        sha256 = compute_file_hash(content)
        uploaded_at = datetime.datetime.now(datetime.UTC).isoformat()
        settings = get_settings()

        blob_path = f"legal-documents/{session_id}/{document_id}.pdf"

        if self.is_configured:
            try:
                client = self._get_client()
                bucket = client.bucket(settings.gcs_bucket)
                blob = bucket.blob(blob_path)

                # Custom metadata
                blob.metadata = {
                    "document_id": document_id,
                    "session_id": session_id,
                    "original_filename": safe_name,
                    "sha256": sha256,
                    "uploaded_at": uploaded_at,
                    "retention_days": str(settings.document_retention_days),
                }

                # Upload with explicit content type (private by default in Google Cloud)
                blob.upload_from_file(
                    io.BytesIO(content),
                    content_type="application/pdf",
                    rewind=True,
                )

                logger.info(
                    "Uploaded document to GCS: gs://%s/%s (size=%d bytes)",
                    settings.gcs_bucket,
                    blob_path,
                    len(content),
                )

                return {
                    "storage_backend": "gcs",
                    "gcs_uri": f"gs://{settings.gcs_bucket}/{blob_path}",
                    "blob_path": blob_path,
                    "bucket": settings.gcs_bucket,
                    "sha256": sha256,
                    "size_bytes": len(content),
                    "uploaded_at": uploaded_at,
                }
            except Exception as exc:
                logger.error("Failed to upload document to GCS: %s", exc)
                raise GCSStorageError(f"Cloud Storage upload failed: {type(exc).__name__}") from exc
        else:
            # Fallback to secure local ephemeral storage in development
            local_dir = settings.upload_dir / session_id
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_dir / f"{document_id}.pdf"
            local_path.write_bytes(content)

            logger.info("GCS not configured; stored document in local scratch: %s", local_path)
            return {
                "storage_backend": "local_scratch",
                "local_path": str(local_path),
                "blob_path": blob_path,
                "sha256": sha256,
                "size_bytes": len(content),
                "uploaded_at": uploaded_at,
            }

    def download_to_temp(self, blob_path: str, session_id: str, document_id: str) -> Path:
        """Download document from GCS into a temporary local path for processing."""
        settings = get_settings()
        local_dir = settings.upload_dir / session_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"{document_id}.pdf"

        if self.is_configured:
            try:
                client = self._get_client()
                bucket = client.bucket(settings.gcs_bucket)
                blob = bucket.blob(blob_path)
                blob.download_to_filename(str(local_path))
                return local_path
            except Exception as exc:
                logger.error("Failed to download blob %s from GCS: %s", blob_path, exc)
                raise GCSStorageError(f"Could not retrieve document from Cloud Storage: {type(exc).__name__}") from exc
        else:
            if local_path.exists():
                return local_path
            raise GCSStorageError(f"Local document not found at {local_path}")

    def delete_document(self, blob_path: str, session_id: str, document_id: str) -> bool:
        """Delete document from GCS and clean up any local temp copies."""
        settings = get_settings()
        deleted = False

        if self.is_configured:
            try:
                client = self._get_client()
                bucket = client.bucket(settings.gcs_bucket)
                blob = bucket.blob(blob_path)
                if blob.exists():
                    blob.delete()
                    deleted = True
                    logger.info("Deleted GCS blob %s", blob_path)
            except Exception as exc:
                logger.warning("Error deleting blob %s from GCS: %s", blob_path, exc)

        # Always clean local temp file
        local_path = settings.upload_dir / session_id / f"{document_id}.pdf"
        if local_path.exists():
            try:
                local_path.unlink()
                deleted = True
            except Exception as exc:
                logger.warning("Could not delete local file %s: %s", local_path, exc)

        return deleted
