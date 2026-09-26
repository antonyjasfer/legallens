"""Security utilities for file validation, sanitization, and header management."""

import hashlib
import re
import secrets
from pathlib import Path

# PDF magic number (first 4 bytes of every valid PDF)
PDF_MAGIC_BYTES = b"%PDF"

# Maximum safe filename length
MAX_FILENAME_LENGTH = 100

# Characters allowed in sanitized filenames
SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9_\-.]")


def sanitize_filename(filename: str) -> str:
    """Sanitize an uploaded filename to prevent path traversal and special characters.

    Strips directory components, replaces unsafe characters, and truncates length.
    """
    # Remove directory components
    name = Path(filename).name
    # Replace unsafe characters
    name = SAFE_FILENAME_PATTERN.sub("_", name)
    # Truncate
    if len(name) > MAX_FILENAME_LENGTH:
        stem = name[:MAX_FILENAME_LENGTH - 4]
        name = f"{stem}.pdf"
    # Ensure non-empty
    if not name or name == ".pdf":
        name = f"upload_{secrets.token_hex(6)}.pdf"
    return name


def validate_pdf_magic(file_bytes: bytes) -> bool:
    """Check if file content begins with the PDF magic number."""
    return file_bytes[:4] == PDF_MAGIC_BYTES


def compute_file_hash(file_bytes: bytes) -> str:
    """Compute SHA-256 hex digest for a file's bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


# Security headers for HTTP responses
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}
