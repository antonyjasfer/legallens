"""Document processing: PDF text extraction and page-level chunking.

Uses PyMuPDF (fitz) for safe local text extraction with page metadata.
"""

import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from app.core.errors import DocumentProcessingError

logger = logging.getLogger("legallens.document_processor")

# Minimum text length to consider a page as having extractable content
MIN_PAGE_TEXT_LENGTH = 10


@dataclass
class PageContent:
    """Extracted text content from a single page."""
    page_number: int  # 1-indexed
    text: str


@dataclass
class ProcessedDocument:
    """Result of processing a PDF document."""
    filename: str
    total_pages: int
    pages: list[PageContent] = field(default_factory=list)
    full_text: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.full_text.strip())


def extract_text_from_pdf(file_bytes: bytes, filename: str) -> ProcessedDocument:
    """Extract text from a PDF file with page-level granularity.

    Args:
        file_bytes: Raw PDF file bytes.
        filename: Original (sanitized) filename.

    Returns:
        ProcessedDocument with page-level text and metadata.

    Raises:
        DocumentProcessingError: If the PDF cannot be opened or has no text.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.warning("Failed to open PDF '%s': %s", filename, exc)
        raise DocumentProcessingError(
            f"Could not open the PDF file. It may be corrupted or encrypted. Error: {exc}"
        ) from exc

    pages: list[PageContent] = []
    all_text_parts: list[str] = []

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            page_num = page_idx + 1  # 1-indexed

            if len(text) >= MIN_PAGE_TEXT_LENGTH:
                pages.append(PageContent(page_number=page_num, text=text))
                all_text_parts.append(f"[Page {page_num}]\n{text}")

        full_text = "\n\n".join(all_text_parts)

        # Extract metadata safely
        meta = {}
        try:
            pdf_meta = doc.metadata or {}
            for key in ("title", "author", "subject", "creator"):
                val = pdf_meta.get(key, "")
                if val:
                    meta[key] = str(val)[:200]  # Limit metadata length
        except Exception as exc:
            logger.debug("Could not read PDF metadata: %s", exc)

        result = ProcessedDocument(
            filename=filename,
            total_pages=len(doc),
            pages=pages,
            full_text=full_text,
            metadata=meta,
        )
    finally:
        doc.close()

    if not result.has_content:
        raise DocumentProcessingError(
            "No extractable text found in the PDF. It may be a scanned image document. "
            "Please provide a text-based PDF."
        )

    logger.info(
        "Processed '%s': %d pages, %d with text, %d chars total",
        filename,
        result.total_pages,
        len(result.pages),
        len(result.full_text),
    )
    return result
