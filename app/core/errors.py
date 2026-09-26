"""Structured application error hierarchy."""


class LegalLensError(Exception):
    """Base error for LegalLens application."""

    def __init__(self, message: str, status_code: int = 500, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or message
        super().__init__(self.message)


class FileValidationError(LegalLensError):
    """Raised when an uploaded file fails validation checks."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class FileTooLargeError(FileValidationError):
    """Raised when an uploaded file exceeds the size limit."""
    pass


class InvalidFileTypeError(FileValidationError):
    """Raised when an uploaded file is not a supported type."""
    pass


class DocumentProcessingError(LegalLensError):
    """Raised when document text extraction fails."""

    def __init__(self, message: str = "Failed to process the uploaded document."):
        super().__init__(message=message, status_code=422)


class GeminiNotConfiguredError(LegalLensError):
    """Raised when Gemini API key is not set."""

    def __init__(self):
        super().__init__(
            message="AI service is not configured. Set GEMINI_API_KEY to enable analysis.",
            status_code=503,
        )


class GeminiAPIError(LegalLensError):
    """Raised when a Gemini API call fails."""

    def __init__(self, message: str = "AI service request failed. Please try again."):
        super().__init__(message=message, status_code=502)


class DocumentNotFoundError(LegalLensError):
    """Raised when a referenced document is not in the session."""

    def __init__(self, doc_id: str):
        super().__init__(
            message=f"Document '{doc_id}' not found in current session.",
            status_code=404,
        )
