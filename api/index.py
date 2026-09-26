"""Vercel Serverless Function entrypoint for LegalLens FastAPI application."""

import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path for Vercel serverless execution
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.main import app as _app  # noqa: E402


class VercelPathAdapter:
    """Restore original request path if rewritten by Vercel serverless router."""

    def __init__(self, asgi_app: Any):
        self.app = asgi_app

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            raw_headers = dict(scope.get("headers", []))
            # Vercel supplies x-matched-path, x-vercel-original-url, or x-forwarded-uri on rewrites
            orig_path = (
                raw_headers.get(b"x-matched-path")
                or raw_headers.get(b"x-vercel-original-url")
                or raw_headers.get(b"x-forwarded-uri")
                or raw_headers.get(b"x-real-path")
            )
            if orig_path:
                decoded = orig_path.decode("utf-8").split("?")[0]
                if decoded and decoded != scope.get("path"):
                    scope["path"] = decoded
                    scope["raw_path"] = decoded.encode("utf-8")

        await self.app(scope, receive, send)


app = VercelPathAdapter(_app)

__all__ = ["app"]
