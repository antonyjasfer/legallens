"""Document Q&A route — evidence-first answers about uploaded documents."""

import logging

from fastapi import APIRouter, HTTPException

from app.api.routes_analysis import get_cached_document
from app.core.errors import GeminiAPIError, GeminiNotConfiguredError
from app.models.schemas import AskRequest
from app.services.analyzer import ask_document

logger = logging.getLogger("legallens.routes.qa")

router = APIRouter(prefix="/api/documents", tags=["qa"])


@router.post("/ask", response_model=dict)
async def ask_document_endpoint(request: AskRequest):
    """Ask a question about a previously uploaded document.

    The answer will:
    - Be grounded in document evidence only
    - Include support_status indicating confidence level
    - Show page numbers and excerpts for supported claims
    - Return NOT_FOUND when information is absent (never guesses)

    Requires document_id from a prior /analyze call.
    """
    # Retrieve cached document
    doc = get_cached_document(request.document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found. Please upload and analyze the document first.",
        )

    try:
        answer = await ask_document(
            doc=doc,
            question=request.question,
            language=request.language,
        )
    except GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=exc.message)
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    return {"answer": answer.model_dump()}
