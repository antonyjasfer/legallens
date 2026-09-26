"""Gemini File Search and Document-Grounded RAG Service.

Implements document indexing, polling for processing completion, grounded question
answering with Google Gemini File API, and deterministic citation extraction
mapped to the Evidence schema.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.core.errors import FileSearchError
from app.models.schemas import Evidence, SupportStatus

logger = logging.getLogger("legallens.file_search")


@dataclass
class IndexedFile:
    """Metadata representing an uploaded and indexed file in Gemini File API."""

    name: str  # e.g., 'files/abc123xyz'
    uri: str
    display_name: str
    mime_type: str
    state: str
    uploaded_at: float = field(default_factory=time.time)


@dataclass
class FileQueryResult:
    """Result of querying Gemini with an indexed document."""

    answer_text: str
    support_status: SupportStatus
    evidence: list[Evidence] = field(default_factory=list)
    model_name: str = ""
    citations_count: int = 0


# Bounded polling configuration for File Search indexing
MAX_POLL_ATTEMPTS: int = 30  # Maximum number of polling iterations
INITIAL_POLL_INTERVAL_S: float = 1.0  # Initial polling interval in seconds
MAX_POLL_INTERVAL_S: float = 5.0  # Cap on exponential backoff interval


class FileSearchService:
    """Service managing document indexing and grounded retrieval via Google Gemini."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or initialize Google GenAI client."""
        if self._client is not None:
            return self._client

        api_key = self.settings.gemini_api_key
        if not api_key:
            raise FileSearchError("Gemini API key is not configured.")

        try:
            from google import genai

            self._client = genai.Client(api_key=api_key)
            return self._client
        except Exception as exc:
            logger.warning("Failed to initialize GenAI client for File Search: %s", exc)
            raise FileSearchError(f"GenAI Client initialization failed: {exc}") from exc

    def upload_and_index(
        self,
        file_path: Path | str,
        display_name: str,
        mime_type: str = "application/pdf",
        max_wait_seconds: int = 60,
    ) -> IndexedFile:
        """Upload a PDF to Gemini File API and wait for indexing completion.

        Args:
            file_path: Local filesystem path to the PDF file.
            display_name: Clean display name for the document.
            mime_type: MIME type (default application/pdf).
            max_wait_seconds: Maximum time to wait for file state to become ACTIVE.

        Returns:
            IndexedFile containing Google File API identifiers.

        Raises:
            FileSearchError: If upload fails or indexing encounters an error.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileSearchError(f"Document file not found at: {path}")

        client = self._get_client()
        try:
            logger.info("Uploading '%s' (%s) to Google Gemini File API...", display_name, mime_type)
            from google.genai import types

            upload_config = types.UploadFileConfig(
                mime_type=mime_type,
                display_name=display_name,
            )
            file_ref = client.files.upload(
                file=str(path),
                config=upload_config,
            )
            logger.info(
                "Uploaded to Gemini File API: %s (initial state: %s)", file_ref.name, file_ref.state
            )

            # Wait for file processing with bounded polling and exponential backoff
            current_file = file_ref
            poll_interval = INITIAL_POLL_INTERVAL_S
            for attempt in range(MAX_POLL_ATTEMPTS):
                if str(current_file.state).upper() not in ("PROCESSING", "FILESTATE.PROCESSING"):
                    break
                time.sleep(min(poll_interval, MAX_POLL_INTERVAL_S))
                poll_interval *= 1.5  # Gradual backoff
                current_file = client.files.get(name=file_ref.name)
                logger.debug(
                    "Polling file %s state: %s (attempt %d/%d)",
                    file_ref.name,
                    current_file.state,
                    attempt + 1,
                    MAX_POLL_ATTEMPTS,
                )
            else:
                logger.warning(
                    "File %s indexing timed out after %d poll attempts",
                    file_ref.name,
                    MAX_POLL_ATTEMPTS,
                )

            final_state = str(current_file.state)
            if "FAILED" in final_state.upper():
                raise FileSearchError(f"Gemini file indexing failed with state: {final_state}")

            logger.info(
                "Document %s is ready for query (state: %s)", current_file.name, final_state
            )
            return IndexedFile(
                name=current_file.name,
                uri=getattr(current_file, "uri", ""),
                display_name=display_name,
                mime_type=mime_type,
                state=final_state,
            )

        except Exception as exc:
            logger.warning("Error uploading/indexing document to Gemini File API: %s", exc)
            if isinstance(exc, FileSearchError):
                raise
            raise FileSearchError(f"Failed to index document with Gemini: {exc}") from exc

    def query_indexed_document(
        self,
        file_name: str,
        question: str,
        document_display_name: str,
        model_name: str | None = None,
    ) -> FileQueryResult:
        """Query an indexed document using Gemini multimodal file grounding.

        Extracts citations, identifies support status, and maps quotes to deterministic Evidence items.
        """
        client = self._get_client()
        model = model_name or self.settings.gemini_model or "gemini-3.8-flash"

        try:
            # Retrieve file reference
            file_ref = client.files.get(name=file_name)
        except Exception as exc:
            logger.warning("Failed to retrieve indexed file %s: %s", file_name, exc)
            raise FileSearchError(f"Indexed document is not accessible: {exc}") from exc

        system_instruction = (
            "You are LegalLens, an evidence-first legal document assistant. "
            "You must answer user questions STRICTLY and SOLELY based on the provided document. "
            "CRITICAL INSTRUCTIONS:\n"
            "1. If the document does not contain the answer, reply EXACTLY:\n"
            "'This cannot be determined from the document you provided.'\n"
            "2. Never hallucinate, extrapolate, or use outside assumptions.\n"
            "3. Whenever answering, quote the exact relevant text, provide the section or clause title, "
            "and indicate the page number if available in the format: [Page X, Section Y: 'quote'].\n"
            "4. Categorize your answer as SUPPORTED if found directly, or NOT_FOUND if absent."
        )

        prompt = (
            f"Document: {document_display_name}\n\n"
            f"Question: {question}\n\n"
            "Please provide a clear, factual answer citing exact sections, clauses, and page numbers."
        )

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,  # Low temperature for strict factual adherence
            )

            # Try primary model, fall back if 503/429 unavailable
            models_to_try = [model]
            for candidate in ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"):
                if candidate not in models_to_try:
                    models_to_try.append(candidate)

            last_exc = None
            response = None
            for m in models_to_try:
                try:
                    logger.info("Querying indexed document %s with model %s", file_name, m)
                    response = client.models.generate_content(
                        model=m,
                        contents=[file_ref, prompt],
                        config=config,
                    )
                    logger.info("Indexed document query handled successfully by model=%s", m)
                    break
                except Exception as exc:
                    last_exc = exc
                    code = getattr(exc, "code", None)
                    logger.warning(
                        "Model %s failed (code=%s): %s; evaluating fallback...",
                        m,
                        code,
                        type(exc).__name__,
                    )
                    if code in (401, 403):
                        break
                    time.sleep(1.0)

            if response is None:
                raise last_exc or FileSearchError("Failed to generate response from indexed file.")

            answer_text = response.text or ""
            logger.info("Received response from Gemini File Search (%d chars)", len(answer_text))

            # Detect NOT_FOUND
            if "cannot be determined from the document" in answer_text.lower():
                return FileQueryResult(
                    answer_text="This cannot be determined from the document you provided.",
                    support_status=SupportStatus.NOT_FOUND,
                    evidence=[],
                    model_name=model,
                    citations_count=0,
                )

            # Parse citations from response text and grounding metadata
            evidence_items = self._extract_evidence_from_response(
                answer_text=answer_text,
                document_name=document_display_name,
            )

            support_status = (
                SupportStatus.SUPPORTED if evidence_items else SupportStatus.PARTIALLY_SUPPORTED
            )
            return FileQueryResult(
                answer_text=answer_text,
                support_status=support_status,
                evidence=evidence_items,
                model_name=model,
                citations_count=len(evidence_items),
            )

        except Exception as exc:
            logger.warning("Error querying indexed file %s: %s", file_name, exc)
            raise FileSearchError(f"Query on indexed document failed: {exc}") from exc

    def _extract_evidence_from_response(
        self,
        answer_text: str,
        document_name: str,
    ) -> list[Evidence]:
        """Extract citations and quotes into deterministic Evidence items."""
        evidence_items: list[Evidence] = []

        # Regex patterns to detect citations like [Page 2, Section 5.1: "quote"] or Section 5.1: "quote"
        quote_patterns = [
            r'\[(?:Page\s*(?P<page>\d+))?(?:,?\s*(?:Section|Clause)\s*(?P<section>[^:\]]+))?:\s*["\'](?P<excerpt>[^"\']+)["\']\]',
            r'(?:Section|Clause)\s*(?P<section>\d+(?:\.\d+)*)[^:\n]*:\s*["\'](?P<excerpt>[^"\']{15,})["\']',
            r'["\'](?P<excerpt>[^"\']{25,})["\']',  # Direct quoted text
        ]

        for pat in quote_patterns:
            for match in re.finditer(pat, answer_text, re.IGNORECASE):
                group_dict = match.groupdict()
                page_str = group_dict.get("page")
                page_num = int(page_str) if page_str and page_str.isdigit() else None
                section_str = (
                    group_dict.get("section", "").strip() if group_dict.get("section") else None
                )
                excerpt = group_dict.get("excerpt", "").strip()

                if (
                    excerpt
                    and len(excerpt) >= 10
                    and not any(e.excerpt.lower() == excerpt.lower() for e in evidence_items)
                ):
                    evidence_items.append(
                        Evidence(
                            document_name=document_name,
                            page_number=page_num,
                            section=section_str,
                            excerpt=excerpt,
                            support_status=SupportStatus.SUPPORTED,
                        )
                    )

        return evidence_items

    def delete_indexed_file(self, file_name: str) -> bool:
        """Safely delete an indexed document from Google Gemini File API."""
        if not file_name or not file_name.startswith("files/"):
            return False

        try:
            client = self._get_client()
            logger.info("Deleting file %s from Gemini File API...", file_name)
            client.files.delete(name=file_name)
            logger.info("Successfully deleted file %s from Gemini File API", file_name)
            return True
        except Exception as exc:
            logger.warning("Failed to delete file %s from Gemini File API: %s", file_name, exc)
            return False

    # ── Async wrappers for blocking SDK operations ────────────────────────

    async def async_upload_and_index(
        self,
        file_path: Path | str,
        display_name: str,
        mime_type: str = "application/pdf",
        max_wait_seconds: int = 60,
    ) -> IndexedFile:
        """Non-blocking wrapper around upload_and_index for async endpoints."""
        return await asyncio.to_thread(
            self.upload_and_index,
            file_path,
            display_name,
            mime_type,
            max_wait_seconds,
        )

    async def async_query_indexed_document(
        self,
        file_name: str,
        question: str,
        document_display_name: str,
        model_name: str | None = None,
    ) -> FileQueryResult:
        """Non-blocking wrapper around query_indexed_document for async endpoints."""
        return await asyncio.to_thread(
            self.query_indexed_document,
            file_name,
            question,
            document_display_name,
            model_name,
        )

    async def async_delete_indexed_file(self, file_name: str) -> bool:
        """Non-blocking wrapper around delete_indexed_file."""
        return await asyncio.to_thread(self.delete_indexed_file, file_name)

    def health_check(self) -> dict[str, Any]:
        """Check File Search API connectivity without creating persistent garbage."""
        if not self.settings.gemini_configured:
            return {"configured": False, "reachable": False, "reason": "GEMINI_API_KEY missing"}

        try:
            client = self._get_client()
            # Test listing files (read-only query)
            files_iter = client.files.list(config={"page_size": 1})
            _ = list(files_iter)
            return {"configured": True, "reachable": True}
        except Exception as exc:
            logger.warning("File Search health check failed: %s", exc)
            return {"configured": True, "reachable": False, "error": str(exc)}
