"""Vercel Serverless Function entrypoint for LegalLens FastAPI application."""

import sys
from pathlib import Path

# Ensure project root is in sys.path for Vercel serverless execution
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.main import app  # noqa: E402

__all__ = ["app"]
