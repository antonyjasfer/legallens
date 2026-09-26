"""Document comparison route — structured change detection between two documents."""

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.core.errors import GeminiAPIError, GeminiNotConfiguredError
from app.core.security import sanitize_filename, validate_pdf_magic
from app.services.analyzer import compare_documents
from app.services.document_processor import extract_text_from_pdf

logger = logging.getLogger("legallens.routes.compare")

router = APIRouter(prefix="/api/documents", tags=["comparison"])


@router.post("/compare", response_model=dict)
async def compare_documents_endpoint(
    file_a: UploadFile = File(..., description="First PDF document (Document A)"),
    file_b: UploadFile = File(..., description="Second PDF document (Document B)"),
    concerns: str = Form(default="[]", description="JSON array of concern categories"),
    custom_concern: str = Form(default="", description="Free-text custom concern"),
    language: str = Form(default="en", description="Explanation language: en, ta, hi"),
):
    """Compare two legal documents with structured change detection.

    Detects and categorizes differences as Added, Removed, Changed, or Unchanged.
    Prioritizes changes related to the user's selected concerns.
    """
    settings = get_settings()

    # Parse concerns
    try:
        concern_list = json.loads(concerns) if concerns else []
        if not isinstance(concern_list, list):
            concern_list = []
    except json.JSONDecodeError:
        concern_list = []

    # Process both files
    docs = []
    for label, upload_file in [("Document A", file_a), ("Document B", file_b)]:
        try:
            content = await upload_file.read()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read {label}: {exc}")
        finally:
            await upload_file.close()

        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{label} is too large. Maximum size is {settings.max_upload_mb} MB.",
            )

        if len(content) == 0:
            raise HTTPException(status_code=400, detail=f"{label} is empty.")

        if not validate_pdf_magic(content):
            raise HTTPException(
                status_code=415,
                detail=f"{label} does not appear to be a valid PDF.",
            )

        safe_name = sanitize_filename(upload_file.filename or f"{label.lower().replace(' ', '_')}.pdf")

        try:
            processed = extract_text_from_pdf(content, safe_name)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not process {label}: {exc}")

        docs.append(processed)

    # Run comparison
    try:
        comparison = await compare_documents(
            doc_a=docs[0],
            doc_b=docs[1],
            concerns=concern_list,
            custom_concern=custom_concern,
            language=language,
        )
    except GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=exc.message)
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    return {
        "document_a": docs[0].filename,
        "document_b": docs[1].filename,
        "comparison": comparison.model_dump(),
    }
