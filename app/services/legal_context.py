"""External legal context research service using Google Search grounding."""

import logging

from app.core.logging import Timer
from app.models.schemas import LegalContextResult, WebCitation
from app.prompts.research import RESEARCH_SYSTEM_PROMPT, build_research_prompt
from app.services.gemini import generate_with_search_grounding

logger = logging.getLogger("legallens.legal_context")


async def research_legal_context(
    query: str,
    jurisdiction: str = "",
) -> LegalContextResult:
    """Research general legal context using Google Search grounding.

    This is explicitly separate from document-grounded answers to help
    users distinguish between:
    - DOCUMENT SAYS (from their uploaded file)
    - EXTERNAL GENERAL INFORMATION (from web sources)
    """
    user_prompt = build_research_prompt(query, jurisdiction)

    with Timer("Legal context research", logger):
        result = await generate_with_search_grounding(
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

    citations = [
        WebCitation(
            title=c.get("title", ""),
            url=c.get("url", ""),
            snippet=c.get("snippet", ""),
        )
        for c in result.get("citations", [])
    ]

    return LegalContextResult(
        query=query,
        context=result.get("context", ""),
        citations=citations,
    )
