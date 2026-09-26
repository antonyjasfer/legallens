"""Document analysis and preparation routes.

Handles PDF upload, validation, analysis, and meeting preparation.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.core.errors import (
    DocumentProcessingError,
    GeminiAPIError,
    GeminiNotConfiguredError,
)
from app.core.security import compute_file_hash, sanitize_filename, validate_pdf_magic
from app.models.schemas import DocumentAnalysis
from app.services.analyzer import analyze_document, prepare_for_professional
from app.services.document_processor import PageContent, ProcessedDocument, extract_text_from_pdf
from app.services.file_search import FileSearchService
from app.services.firestore import FirestoreService
from app.services.gcs import GCSService

logger = logging.getLogger("legallens.routes.analysis")

router = APIRouter(prefix="/api/documents", tags=["analysis"])

# In-memory document cache keyed by SHA-256 hash
# Stores ProcessedDocument and analysis results for the session
_document_cache: dict[str, ProcessedDocument] = {}
_analysis_cache: dict[str, DocumentAnalysis] = {}


def _serialize_processed_doc(doc: ProcessedDocument) -> dict[str, Any]:
    return {
        "filename": doc.filename,
        "total_pages": doc.total_pages,
        "pages": [{"page_number": p.page_number, "text": p.text} for p in doc.pages],
        "full_text": doc.full_text,
        "metadata": doc.metadata,
    }


def _deserialize_processed_doc(data: dict[str, Any]) -> ProcessedDocument:
    pages = [
        PageContent(page_number=p["page_number"], text=p["text"]) for p in data.get("pages", [])
    ]
    return ProcessedDocument(
        filename=data["filename"],
        total_pages=data["total_pages"],
        pages=pages,
        full_text=data.get("full_text", ""),
        metadata=data.get("metadata", {}),
    )


def _persist_document_cache(doc_id: str, doc: ProcessedDocument) -> None:
    _document_cache[doc_id] = doc
    try:
        settings = get_settings()
        cache_dir = settings.upload_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{doc_id}.json"
        cache_file.write_text(json.dumps(_serialize_processed_doc(doc)), encoding="utf-8")
    except Exception as exc:
        logger.debug("Disk cache write failed for %s: %s", doc_id[:12], exc)


async def _validate_and_process_upload(file: UploadFile) -> tuple[ProcessedDocument, str, bytes]:
    """Validate an uploaded file and extract text.

    Returns:
        Tuple of (ProcessedDocument, document_id, raw_bytes).

    Raises:
        HTTPException on validation or processing failure.
    """
    settings = get_settings()

    # Read file content
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {exc}")
    finally:
        await file.close()

    # Size check
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_upload_mb} MB.",
        )

    # Empty file check
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # MIME type check
    if file.content_type and file.content_type not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Only PDF files are accepted.",
        )

    # PDF magic number check
    if not validate_pdf_magic(content):
        raise HTTPException(
            status_code=415,
            detail="File does not appear to be a valid PDF (invalid file signature).",
        )

    # Sanitize filename
    original_name = file.filename or "document.pdf"
    safe_name = sanitize_filename(original_name)

    # Compute document hash for caching
    doc_id = compute_file_hash(content)

    # Check cache
    if doc_id in _document_cache:
        logger.info("Document '%s' found in cache (hash=%s)", safe_name, doc_id[:12])
        return _document_cache[doc_id], doc_id, content

    # Extract text (run in thread to avoid blocking event loop with PyMuPDF C I/O)
    try:
        processed = await asyncio.to_thread(extract_text_from_pdf, content, safe_name)
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=422, detail=exc.message)

    # Cache the processed document
    _persist_document_cache(doc_id, processed)
    logger.info("Document cached: hash=%s, name=%s", doc_id[:12], safe_name)

    return processed, doc_id, content


@router.post("/analyze", response_model=dict)
async def analyze_document_endpoint(
    file: UploadFile = File(..., description="PDF document to analyze"),
    concerns: str = Form(default="[]", description="JSON array of concern categories"),
    custom_concern: str = Form(default="", description="Free-text custom concern"),
    language: str = Form(default="en", description="Explanation language: en, ta, hi"),
):
    """Upload and analyze a legal document with personalized concerns.

    The analysis pipeline:
    1. Validate and extract text from the PDF (with Document AI fallback if scanned)
    2. Upload to private Google Cloud Storage (or secure local scratch)
    3. Index in Gemini File Search for evidence retrieval
    4. Store metadata in Google Cloud Firestore
    5. Generate structured analysis via Gemini with evidence-first prompting
    6. Run deterministic verification on the output
    """
    # Parse concerns from JSON string
    try:
        concern_list = json.loads(concerns) if concerns else []
        if not isinstance(concern_list, list):
            concern_list = []
    except json.JSONDecodeError:
        concern_list = []

    # Validate and process upload
    processed_doc, doc_id, raw_bytes = await _validate_and_process_upload(file)
    session_id = str(uuid.uuid4())[:8]

    # Save to disk for GCS and File Search indexing
    settings = get_settings()
    temp_path = settings.upload_dir / session_id / f"{doc_id}.pdf"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(temp_path.write_bytes, raw_bytes)

    # Store in GCS
    gcs_svc = GCSService.get_instance()
    gcs_info = {}
    try:
        gcs_info = gcs_svc.upload_document(
            content=raw_bytes,
            original_filename=processed_doc.filename,
            session_id=session_id,
            document_id=doc_id,
        )
    except Exception as exc:
        logger.warning("GCS upload warning: %s", exc)

    # Index in Gemini File Search if configured and file exists on disk
    file_search_doc_name = None
    try:
        fs_svc = FileSearchService()
        if fs_svc.settings.gemini_configured and temp_path.exists():
            indexed_file = await fs_svc.async_upload_and_index(
                temp_path,
                display_name=f"{doc_id[:16]}__{processed_doc.filename}",
            )
            file_search_doc_name = indexed_file.name
            logger.info("Indexed in Gemini File Search: %s", file_search_doc_name)
    except Exception as exc:
        logger.warning("Gemini File Search indexing skipped: %s", exc)
    finally:
        # Clean up temporary file after File Search indexing to prevent disk accumulation
        try:
            if temp_path.exists():
                temp_path.unlink()
                if temp_path.parent.exists() and not any(temp_path.parent.iterdir()):
                    temp_path.parent.rmdir()
        except OSError as exc:
            logger.debug("Temp file cleanup: %s", exc)

    # Persist metadata to Firestore
    try:
        firestore_svc = FirestoreService.get_instance()
        firestore_svc.save_document_metadata(
            {
                "document_id": doc_id,
                "session_id": session_id,
                "original_filename": processed_doc.filename,
                "gcs_object": gcs_info.get("blob_path", ""),
                "sha256": doc_id,
                "mime_type": "application/pdf",
                "file_search_document_name": file_search_doc_name or "",
                "document_ai_used": processed_doc.metadata.get("source")
                == "Google Document AI Layout Parser",
                "selected_concerns": concern_list,
                "language": language,
            }
        )
    except Exception as exc:
        logger.warning("Firestore metadata persistence warning: %s", exc)

    # Update processed_doc metadata with Cloud references
    processed_doc.metadata["session_id"] = session_id
    processed_doc.metadata["gcs_object"] = gcs_info.get("blob_path", "")
    if file_search_doc_name:
        processed_doc.metadata["file_search_document_name"] = file_search_doc_name
    _persist_document_cache(doc_id, processed_doc)

    # Run analysis
    try:
        analysis = await analyze_document(
            doc=processed_doc,
            concerns=concern_list,
            custom_concern=custom_concern,
            language=language,
        )
    except GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=exc.message)
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    # Cache analysis (memory + disk)
    _analysis_cache[doc_id] = analysis
    try:
        cache_file = settings.upload_dir / "cache" / f"{doc_id}_analysis.json"
        cache_file.write_text(analysis.model_dump_json(), encoding="utf-8")
    except Exception as exc:
        logger.debug("Disk cache write failed for analysis %s: %s", doc_id[:12], exc)

    return {
        "document_id": doc_id,
        "document_name": processed_doc.filename,
        "total_pages": processed_doc.total_pages,
        "analysis": analysis.model_dump(),
        "file_search_indexed": bool(file_search_doc_name),
        "metadata": processed_doc.metadata,
    }


@router.post("/prepare", response_model=dict)
async def prepare_questions_endpoint(
    document_id: str = Form(..., description="Document ID from analysis"),
    language: str = Form(default="en"),
):
    """Generate a meeting preparation sheet for consulting a legal professional.

    Requires a prior analysis of the document (document_id from /analyze).
    """
    analysis = get_cached_analysis(document_id)
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail="No analysis found for this document. Please analyze the document first.",
        )

    prep = await prepare_for_professional(analysis, language)

    return {"preparation": prep.model_dump()}


@router.delete("/{document_id}", response_model=dict)
async def delete_document_endpoint(document_id: str):
    """Privacy cleanup: Delete document across GCS, Firestore, File Search, and local caches."""
    cleaned_services: list[str] = []
    processed = _document_cache.get(document_id)
    meta = processed.metadata if processed else {}

    # 1. Delete GCS object
    gcs_svc = GCSService.get_instance()
    session_id = meta.get("session_id", "default")
    blob_path = meta.get("gcs_object", f"legal-documents/{session_id}/{document_id}.pdf")
    if gcs_svc.delete_document(blob_path, session_id, document_id):
        cleaned_services.append("cloud_storage")

    # 2. Delete Gemini File Search index
    fs_name = meta.get("file_search_document_name")
    if fs_name:
        try:
            FileSearchService().delete_indexed_file(fs_name)
            cleaned_services.append("file_search")
        except Exception as exc:
            logger.warning("Could not delete from File Search: %s", exc)

    # 3. Delete Firestore metadata
    firestore_svc = FirestoreService.get_instance()
    if firestore_svc.delete_document_metadata(document_id):
        cleaned_services.append("firestore")

    # 4. Remove from local caches (memory + disk)
    _document_cache.pop(document_id, None)
    _analysis_cache.pop(document_id, None)
    try:
        settings = get_settings()
        (settings.upload_dir / "cache" / f"{document_id}.json").unlink(missing_ok=True)
        (settings.upload_dir / "cache" / f"{document_id}_analysis.json").unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Cache file unlink warning: %s", exc)
    cleaned_services.append("local_cache")

    return {
        "status": "deleted",
        "document_id": document_id,
        "cleaned_services": cleaned_services,
    }


def get_cached_document(doc_id: str) -> ProcessedDocument | None:
    """Retrieve a cached document by ID (used by Q&A route)."""
    # 1. In-memory cache
    if doc_id in _document_cache:
        return _document_cache[doc_id]

    # 2. Ephemeral disk cache (/tmp)
    try:
        settings = get_settings()
        cache_file = settings.upload_dir / "cache" / f"{doc_id}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            doc = _deserialize_processed_doc(data)
            _document_cache[doc_id] = doc
            return doc
    except Exception as exc:
        logger.debug("Disk cache read failed for %s: %s", doc_id[:12], exc)

    # 3. Gemini File Search Cloud Fallback (resolves across serverless instances)
    try:
        settings = get_settings()
        if settings.gemini_configured:
            from app.services.file_search import FileSearchService

            fs_svc = FileSearchService()
            client = fs_svc._get_client()
            for f in client.files.list():
                d_name = getattr(f, "display_name", "") or ""
                if doc_id[:16] in d_name:
                    original_name = d_name.split("__", 1)[-1] if "__" in d_name else d_name
                    doc = ProcessedDocument(
                        filename=original_name,
                        total_pages=1,
                        pages=[],
                        full_text="",
                        metadata={"file_search_document_name": f.name},
                    )
                    _document_cache[doc_id] = doc
                    return doc
    except Exception as exc:
        logger.debug("Gemini file lookup fallback failed for %s: %s", doc_id[:12], exc)

    return None


def get_cached_analysis(doc_id: str) -> DocumentAnalysis | None:
    """Retrieve a cached analysis by ID."""
    if doc_id in _analysis_cache:
        return _analysis_cache[doc_id]
    try:
        settings = get_settings()
        cache_file = settings.upload_dir / "cache" / f"{doc_id}_analysis.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            analysis = DocumentAnalysis.model_validate(data)
            _analysis_cache[doc_id] = analysis
            return analysis
    except Exception as exc:
        logger.debug("Disk cache read failed for analysis %s: %s", doc_id[:12], exc)
    return None
