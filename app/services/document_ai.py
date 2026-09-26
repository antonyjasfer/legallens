"""Google Cloud Document AI Layout Parser integration for scanned or complex legal documents.

Evaluates PDF text extraction quality first, only invoking Document AI Layout Parser
when standard extraction is insufficient (e.g., scanned documents or image-only PDFs).
Degrades gracefully when Document AI is not configured or in local development.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.core.errors import DocumentAIError

logger = logging.getLogger("legallens.document_ai")


@dataclass
class DocumentAIPage:
    """Document AI extracted page with structural annotations."""
    page_number: int
    text: str
    paragraphs: list[str] = field(default_factory=list)
    tables_count: int = 0


@dataclass
class DocumentAIResult:
    """Result of processing a document with Google Cloud Document AI."""
    raw_text: str
    total_pages: int
    pages: list[DocumentAIPage] = field(default_factory=list)
    processor_name: str = ""
    success: bool = True
    error_message: str | None = None


class DocumentAIService:
    """Service for document layout parsing using Google Cloud Document AI."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        """Check if Document AI is enabled and configured."""
        return (
            bool(self.settings.document_ai_enabled)
            and bool(self.settings.document_ai_processor_id)
            and bool(self.settings.google_cloud_project)
        )

    def _get_client(self) -> Any:
        """Get or initialize DocumentProcessorServiceClient using ADC."""
        if self._client is not None:
            return self._client

        try:
            from google.cloud import documentai
            # Use regional endpoint if specified (e.g., us-documentai.googleapis.com)
            location = self.settings.google_cloud_location.split("-")[0] if "-" in self.settings.google_cloud_location else self.settings.google_cloud_location
            client_options = None
            if location in ("us", "eu"):
                client_options = {"api_endpoint": f"{location}-documentai.googleapis.com"}

            self._client = documentai.DocumentProcessorServiceClient(client_options=client_options)
            return self._client
        except Exception as exc:
            logger.warning("Failed to initialize Document AI client: %s", exc)
            raise DocumentAIError(f"Document AI client initialization failed: {exc}") from exc

    def evaluate_needs_document_ai(self, total_pages: int, extracted_chars: int) -> bool:
        """Evaluate if PDF requires Document AI Layout Parser.

        True if:
        - 0 text was extracted (scanned/raster PDF)
        - Average text density < 100 characters per page
        """
        if total_pages <= 0:
            return True
        avg_chars = extracted_chars / total_pages
        return avg_chars < 100

    def parse_layout(self, file_bytes: bytes, mime_type: str = "application/pdf") -> DocumentAIResult:
        """Process document through Google Document AI Layout Parser.

        Args:
            file_bytes: Raw bytes of the document (PDF, TIFF, etc.).
            mime_type: MIME type of the document.

        Returns:
            DocumentAIResult with extracted layout text and page breakdown.

        Raises:
            DocumentAIError: If processing fails and cannot be recovered.
        """
        if not self.is_configured:
            logger.info("Document AI is not configured or disabled; skipping layout parsing.")
            return DocumentAIResult(
                raw_text="",
                total_pages=0,
                success=False,
                error_message="Document AI not configured",
            )

        try:
            from google.cloud import documentai
            client = self._get_client()

            # Format processor name: projects/{project}/locations/{location}/processors/{processor_id}
            processor_id = self.settings.document_ai_processor_id
            location = self.settings.google_cloud_location
            if "/" in processor_id:
                name = processor_id
            else:
                name = client.processor_path(
                    self.settings.google_cloud_project,
                    location,
                    processor_id,
                )

            raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
            request = documentai.ProcessDocumentRequest(name=name, raw_document=raw_document)

            logger.info("Sending document (%d bytes) to Document AI processor: %s", len(file_bytes), name)
            response = client.process_document(request=request)
            document = response.document

            pages: list[DocumentAIPage] = []
            for idx, p in enumerate(document.pages):
                page_num = idx + 1
                page_text = ""
                paragraphs: list[str] = []

                # Extract layout paragraphs if available
                for paragraph in p.paragraphs:
                    start_idx = paragraph.layout.text_anchor.text_segments[0].start_index if paragraph.layout.text_anchor.text_segments else 0
                    end_idx = paragraph.layout.text_anchor.text_segments[0].end_index if paragraph.layout.text_anchor.text_segments else 0
                    p_text = document.text[start_idx:end_idx].strip()
                    if p_text:
                        paragraphs.append(p_text)

                page_text = "\n\n".join(paragraphs) if paragraphs else ""
                pages.append(
                    DocumentAIPage(
                        page_number=page_num,
                        text=page_text,
                        paragraphs=paragraphs,
                        tables_count=len(p.tables),
                    )
                )

            full_text = document.text or "\n\n".join(p.text for p in pages)
            logger.info(
                "Document AI successfully processed %d pages, %d chars total",
                len(pages),
                len(full_text),
            )

            return DocumentAIResult(
                raw_text=full_text,
                total_pages=len(pages),
                pages=pages,
                processor_name=name,
                success=True,
            )

        except Exception as exc:
            logger.warning("Document AI layout parsing failed: %s", exc)
            return DocumentAIResult(
                raw_text="",
                total_pages=0,
                success=False,
                error_message=str(exc),
            )

    def health_check(self) -> dict[str, Any]:
        """Check Document AI configuration status."""
        configured = self.is_configured
        reachable = False
        error = None

        if configured:
            try:
                self._get_client()
                reachable = True
            except Exception as exc:
                error = str(exc)

        return {
            "configured": configured,
            "reachable": reachable,
            "processor_configured": bool(self.settings.document_ai_processor_id),
            "error": error,
        }
