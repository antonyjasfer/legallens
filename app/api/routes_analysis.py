"""Document analysis and preparation routes.

Handles PDF upload, validation, analysis, and meeting preparation.
"""

import json
import logging

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
from app.services.document_processor import ProcessedDocument, extract_text_from_pdf

logger = logging.getLogger("legallens.routes.analysis")

router = APIRouter(prefix="/api/documents", tags=["analysis"])

# In-memory document cache keyed by SHA-256 hash
# Stores ProcessedDocument and analysis results for the session
_document_cache: dict[str, ProcessedDocument] = {}
_analysis_cache: dict[str, DocumentAnalysis] = {}


async def _validate_and_process_upload(file: UploadFile) -> tuple[ProcessedDocument, str]:
    """Validate an uploaded file and extract text.

    Returns:
        Tuple of (ProcessedDocument, document_id).

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
        return _document_cache[doc_id], doc_id

    # Extract text
    try:
        processed = extract_text_from_pdf(content, safe_name)
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=422, detail=exc.message)

    # Cache the processed document
    _document_cache[doc_id] = processed
    logger.info("Document cached: hash=%s, name=%s", doc_id[:12], safe_name)

    return processed, doc_id


@router.post("/analyze", response_model=dict)
async def analyze_document_endpoint(
    file: UploadFile = File(..., description="PDF document to analyze"),
    concerns: str = Form(default="[]", description="JSON array of concern categories"),
    custom_concern: str = Form(default="", description="Free-text custom concern"),
    language: str = Form(default="en", description="Explanation language: en, ta, hi"),
):
    """Upload and analyze a legal document with personalized concerns.

    The analysis pipeline:
    1. Validate and extract text from the PDF
    2. Generate structured analysis via Gemini with evidence-first prompting
    3. Run deterministic verification on the output
    4. Return validated, structured results

    Returns document_id for subsequent Q&A queries.
    """
    # Parse concerns from JSON string
    try:
        concern_list = json.loads(concerns) if concerns else []
        if not isinstance(concern_list, list):
            concern_list = []
    except json.JSONDecodeError:
        concern_list = []

    # Validate and process upload
    processed_doc, doc_id = await _validate_and_process_upload(file)

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

    # Cache analysis
    _analysis_cache[doc_id] = analysis

    return {
        "document_id": doc_id,
        "document_name": processed_doc.filename,
        "total_pages": processed_doc.total_pages,
        "analysis": analysis.model_dump(),
    }


@router.post("/prepare", response_model=dict)
async def prepare_questions_endpoint(
    document_id: str = Form(..., description="Document ID from analysis"),
    language: str = Form(default="en"),
):
    """Generate a meeting preparation sheet for consulting a legal professional.

    Requires a prior analysis of the document (document_id from /analyze).
    """
    if document_id not in _analysis_cache:
        raise HTTPException(
            status_code=404,
            detail="No analysis found for this document. Please analyze the document first.",
        )

    analysis = _analysis_cache[document_id]
    prep = await prepare_for_professional(analysis, language)

    return {"preparation": prep.model_dump()}


def get_cached_document(doc_id: str) -> ProcessedDocument | None:
    """Retrieve a cached document by ID (used by Q&A route)."""
    return _document_cache.get(doc_id)


def get_cached_analysis(doc_id: str) -> DocumentAnalysis | None:
    """Retrieve a cached analysis by ID."""
    return _analysis_cache.get(doc_id)
