"""External legal context research route using Google Search grounding.

This endpoint is SEPARATE from document-grounded answers to clearly
distinguish between:
  - DOCUMENT SAYS (from uploaded files)
  - EXTERNAL GENERAL INFORMATION (from web sources)
"""

import logging

from fastapi import APIRouter, HTTPException

from app.core.errors import GeminiAPIError, GeminiNotConfiguredError
from app.models.schemas import ResearchRequest
from app.services.legal_context import research_legal_context

logger = logging.getLogger("legallens.routes.research")

router = APIRouter(prefix="/api", tags=["research"])


@router.post("/legal-context", response_model=dict)
async def research_legal_context_endpoint(request: ResearchRequest):
    """Research general legal context using Google Search grounding.

    Results are labeled as external web information and include clickable
    citations. This is NOT from the user's uploaded document.
    """
    try:
        result = await research_legal_context(
            query=request.query,
            jurisdiction=request.jurisdiction,
        )
    except GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=exc.message)
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    return {"result": result.model_dump()}
