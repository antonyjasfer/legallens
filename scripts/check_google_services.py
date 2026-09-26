"""End-to-end Google Cloud and Gemini services connectivity test script.

Tests each service integration safely without leaking credentials, tokens, or private data.
Exits with code 0 if all required services pass; non-zero if a required service fails.
"""

import sys
from pathlib import Path

# Add project root to sys.path so app imports work
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.config import get_settings  # noqa: E402
from app.services.document_ai import DocumentAIService  # noqa: E402
from app.services.file_search import FileSearchService  # noqa: E402
from app.services.firestore import FirestoreService  # noqa: E402
from app.services.gcs import GCSService  # noqa: E402
from app.services.gemini import get_gemini_service  # noqa: E402


def format_status(name: str, status: str, detail: str = "") -> None:
    padding = 24 - len(name)
    dots = "." * max(padding, 3)
    if detail:
        print(f"{name} {dots} {status} ({detail})")
    else:
        print(f"{name} {dots} {status}")


def check_gemini() -> bool:
    """Test Gemini Developer API connectivity with sample prompt."""
    gemini_svc = get_gemini_service()
    settings = get_settings()
    if not settings.gemini_configured:
        format_status("Gemini", "FAIL", "GEMINI_API_KEY missing in .env")
        return False

    try:
        client = gemini_svc.get_client()
        from google.genai import types
        models_to_try = [settings.gemini_model]
        if settings.gemini_model != "gemini-2.5-flash":
            models_to_try.append("gemini-2.5-flash")

        resp = None
        for m in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents="Reply exactly LEGALLENS_OK",
                    config=types.GenerateContentConfig(max_output_tokens=10),
                )
                if resp and "LEGALLENS_OK" in (resp.text or ""):
                    format_status("Gemini", "PASS", f"model: {m}")
                    return True
            except Exception:  # noqa: S112
                continue

        if resp and resp.text:
            format_status("Gemini", "PASS", f"response received: {resp.text.strip()[:20]}")
            return True

        format_status("Gemini", "FAIL", "Empty or unexpected response")
        return False
    except Exception as exc:
        format_status("Gemini", "FAIL", type(exc).__name__)
        return False


def check_file_search() -> bool:
    """Test Gemini File Search API connectivity without leaving junk files."""
    file_search_svc = FileSearchService()
    health = file_search_svc.health_check()
    if health.get("reachable"):
        format_status("File Search", "PASS")
        return True
    elif not health.get("configured"):
        format_status("File Search", "FAIL", "Unconfigured")
        return False
    else:
        format_status("File Search", "FAIL", health.get("error", "Unreachable")[:40])
        return False


async def check_gcs() -> bool:
    """Test Google Cloud Storage bucket accessibility."""
    gcs_svc = GCSService.get_instance()
    health = await gcs_svc.health_check()
    if health.get("reachable"):
        format_status("Cloud Storage", "PASS", f"bucket: {gcs_svc.settings.gcs_bucket}")
        return True
    elif not health.get("configured"):
        format_status("Cloud Storage", "OPTIONAL", "GCS_BUCKET not set (local scratch fallback active)")
        return True
    else:
        format_status("Cloud Storage", "FAIL", health.get("error", "Bucket not reachable")[:40])
        return False


async def check_firestore() -> bool:
    """Test Firestore database connectivity."""
    firestore_svc = FirestoreService.get_instance()
    health = await firestore_svc.health_check()
    if health.get("reachable"):
        format_status("Firestore", "PASS", f"db: {health.get('database')}")
        return True
    elif not health.get("configured"):
        format_status("Firestore", "OPTIONAL", "Firestore not set (in-memory metadata fallback active)")
        return True
    else:
        format_status("Firestore", "FAIL", health.get("error", "Database not reachable")[:40])
        return False


def check_document_ai() -> bool:
    """Test Document AI processor configuration."""
    doc_ai_svc = DocumentAIService()
    health = doc_ai_svc.health_check()
    if health.get("reachable"):
        format_status("Document AI", "PASS", "Layout Parser ready")
        return True
    elif not health.get("configured"):
        format_status("Document AI", "OPTIONAL", "DOCUMENT_AI_ENABLED=false (PyMuPDF local OCR active)")
        return True
    else:
        format_status("Document AI", "FAIL", health.get("error", "Processor unreachable")[:40])
        return False


async def main() -> int:
    print("============================================================")
    print("LegalLens Google Cloud & Gemini Service Connectivity Check")
    print("============================================================")

    gemini_ok = check_gemini()
    file_search_ok = check_file_search()
    gcs_ok = await check_gcs()
    firestore_ok = await check_firestore()
    doc_ai_ok = check_document_ai()

    print("============================================================")
    _ = (gcs_ok, firestore_ok, doc_ai_ok)
    all_required_passed = gemini_ok and file_search_ok

    if all_required_passed:
        print("Required Google AI services are connected and functional!")
        return 0
    else:
        print("Required Google services check failed. Review configuration above.")
        return 1


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
