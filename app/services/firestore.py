"""Google Cloud Firestore service for session and document metadata.

Stores ONLY lightweight operational and tracking metadata in:
- documents/{document_id}
- sessions/{session_id}

NEVER stores raw legal document text, contract content, or API keys.
Degrades cleanly to an in-memory repository when Firestore is unconfigured in development.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from google.cloud import firestore

from app.config import get_settings
from app.core.errors import FirestoreError

logger = logging.getLogger("legallens.firestore")


class FirestoreService:
    """Manages document and session metadata persistence in Google Cloud Firestore."""

    _instance: FirestoreService | None = None

    def __init__(self) -> None:
        self._client: firestore.Client | None = None
        self._memory_documents: dict[str, dict[str, Any]] = {}
        self._memory_sessions: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> FirestoreService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.google_cloud_project and settings.firestore_database)

    def _get_client(self) -> firestore.Client:
        if self._client is None:
            settings = get_settings()
            try:
                self._client = firestore.Client(
                    project=settings.google_cloud_project,
                    database=settings.firestore_database,
                )
            except Exception as exc:
                logger.warning("Could not initialize Firestore client: %s", exc)
                raise FirestoreError(f"Firestore initialization failed: {type(exc).__name__}") from exc
        return self._client

    async def health_check(self) -> dict[str, Any]:
        """Check Firestore connectivity without leaking sensitive project details."""
        settings = get_settings()
        if not self.is_configured:
            return {
                "configured": False,
                "reachable": False,
                "database": settings.firestore_database,
                "message": "Running in-memory metadata mode",
            }

        try:
            client = self._get_client()
            # Perform a lightweight read/collection list
            collections = list(client.collections(page_size=1))
            return {
                "configured": True,
                "reachable": True,
                "database": settings.firestore_database,
                "collections_found": len(collections),
            }
        except Exception as exc:
            logger.warning("Firestore health check failed: %s", type(exc).__name__)
            return {
                "configured": True,
                "reachable": False,
                "database": settings.firestore_database,
                "error": type(exc).__name__,
            }

    def save_document_metadata(self, metadata: dict[str, Any]) -> None:
        """Save document metadata to documents/{document_id}."""
        doc_id = metadata.get("document_id")
        if not doc_id:
            raise ValueError("document_id is required in metadata")

        clean_meta = {
            "document_id": doc_id,
            "session_id": metadata.get("session_id", "default"),
            "original_filename": metadata.get("original_filename", ""),
            "gcs_object": metadata.get("gcs_object", ""),
            "sha256": metadata.get("sha256", ""),
            "mime_type": metadata.get("mime_type", "application/pdf"),
            "size_bytes": metadata.get("size_bytes", 0),
            "total_pages": metadata.get("total_pages", 1),
            "created_at": metadata.get("created_at") or datetime.datetime.now(datetime.UTC).isoformat(),
            "processing_status": metadata.get("processing_status", "PENDING"),
            "file_search_store_name": metadata.get("file_search_store_name", ""),
            "file_search_document_name": metadata.get("file_search_document_name", ""),
            "document_ai_used": metadata.get("document_ai_used", False),
            "selected_concerns": metadata.get("selected_concerns", []),
            "language": metadata.get("language", "en"),
        }

        # Keep in local memory cache
        self._memory_documents[doc_id] = clean_meta

        if self.is_configured:
            try:
                client = self._get_client()
                doc_ref = client.collection("documents").document(doc_id)
                doc_ref.set(clean_meta, merge=True)
                logger.info("Persisted metadata to Firestore: documents/%s", doc_id[:12])
            except Exception as exc:
                logger.warning("Firestore write failed, retained in memory: %s", exc)

    def get_document_metadata(self, document_id: str) -> dict[str, Any] | None:
        """Retrieve metadata for a document."""
        if self.is_configured:
            try:
                client = self._get_client()
                doc_ref = client.collection("documents").document(document_id)
                snapshot = doc_ref.get()
                if snapshot.exists:
                    return snapshot.to_dict()
            except Exception as exc:
                logger.warning("Firestore read failed, falling back to memory: %s", exc)

        return self._memory_documents.get(document_id)

    def update_document_status(self, document_id: str, status: str, **kwargs: Any) -> None:
        """Update processing status and optional fields."""
        updates: dict[str, Any] = {"processing_status": status, "updated_at": datetime.datetime.now(datetime.UTC).isoformat()}
        updates.update(kwargs)

        if document_id in self._memory_documents:
            self._memory_documents[document_id].update(updates)

        if self.is_configured:
            try:
                client = self._get_client()
                doc_ref = client.collection("documents").document(document_id)
                doc_ref.update(updates)
            except Exception as exc:
                logger.warning("Firestore update failed for %s: %s", document_id, exc)

    def delete_document_metadata(self, document_id: str) -> bool:
        """Remove document metadata upon document deletion or privacy cleanup."""
        deleted = False
        if document_id in self._memory_documents:
            del self._memory_documents[document_id]
            deleted = True

        if self.is_configured:
            try:
                client = self._get_client()
                client.collection("documents").document(document_id).delete()
                deleted = True
                logger.info("Deleted Firestore document metadata: documents/%s", document_id[:12])
            except Exception as exc:
                logger.warning("Error deleting Firestore document %s: %s", document_id, exc)

        return deleted
