"""Health check endpoint."""

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check() -> dict:
    """Application health check.

    Returns service status and whether the AI backend is configured.
    """
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "gemini_configured": settings.gemini_configured,
    }
