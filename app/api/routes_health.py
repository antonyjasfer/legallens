"""Health check endpoint."""

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check() -> dict:
    """Application health check."""
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "gemini_configured": settings.gemini_configured,
    }


@router.get("/api/health/google")
async def google_health_check() -> dict:
    """Check configuration and reachability of all Google Cloud and Gemini services.

    Reports status without exposing sensitive credentials, tokens, or keys.
    """
    from app.services.document_ai import DocumentAIService
    from app.services.file_search import FileSearchService
    from app.services.firestore import FirestoreService
    from app.services.gcs import GCSService
    from app.services.gemini import get_gemini_service

    gemini_svc = get_gemini_service()
    file_search_svc = FileSearchService()
    gcs_svc = GCSService.get_instance()
    firestore_svc = FirestoreService.get_instance()
    doc_ai_svc = DocumentAIService()

    gemini_health = await gemini_svc.health_check()
    file_search_health = file_search_svc.health_check()
    gcs_health = await gcs_svc.health_check()
    firestore_health = await firestore_svc.health_check()
    doc_ai_health = doc_ai_svc.health_check()

    return {
        "gemini": {
            "configured": gemini_health.get("configured", False),
            "reachable": gemini_health.get("reachable", False),
            "model": gemini_health.get("model", "gemini-3.8-flash"),
        },
        "file_search": {
            "configured": file_search_health.get("configured", False),
            "reachable": file_search_health.get("reachable", False),
        },
        "cloud_storage": {
            "configured": gcs_health.get("configured", False),
            "bucket": gcs_health.get("bucket", "unconfigured"),
            "reachable": gcs_health.get("reachable", False),
        },
        "firestore": {
            "configured": firestore_health.get("configured", False),
            "reachable": firestore_health.get("reachable", False),
        },
        "document_ai": {
            "configured": doc_ai_health.get("configured", False),
            "reachable": doc_ai_health.get("reachable", False),
        },
    }
