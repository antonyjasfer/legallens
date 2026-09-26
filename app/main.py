"""LegalLens — Evidence-First Legal Document Navigator.

Main FastAPI application with security middleware, error handlers, and route registration.
"""

import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_analysis import router as analysis_router
from app.api.routes_compare import router as compare_router
from app.api.routes_health import router as health_router
from app.api.routes_qa import router as qa_router
from app.api.routes_research import router as research_router
from app.config import get_settings
from app.core.errors import LegalLensError
from app.core.logging import generate_request_id, request_id_var, setup_logging
from app.core.security import SECURITY_HEADERS

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    settings = get_settings()
    logger.info(
        "Starting %s v%s (env=%s, gemini=%s)",
        settings.app_name,
        settings.app_version,
        settings.app_env,
        "configured" if settings.gemini_configured else "NOT configured",
    )
    # Ensure upload directory exists
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Evidence-First Legal Document Navigator — understand what matters, verify where it came from.",
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
    )

    # ── GZip Compression ───────────────────────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # ── CORS ───────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    # ── Security Headers Middleware ────────────────────────────────────────
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        # Set request ID for logging
        req_id = generate_request_id()
        request_id_var.set(req_id)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Add security headers
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["X-Request-ID"] = req_id

        # Cache-Control for static assets (immutable content-hashed resources)
        path = request.url.path
        if path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        elif path == "/":
            response.headers["Cache-Control"] = "no-cache"

        # Log request
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        return response

    # ── Error Handlers ─────────────────────────────────────────────────────
    @app.exception_handler(LegalLensError)
    async def legallens_error_handler(request: Request, exc: LegalLensError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        logger.error("Unhandled error: %s: %s", type(exc).__name__, exc)
        message = "An internal error occurred. Please try again."
        if not settings.is_production:
            message = f"{type(exc).__name__}: {exc}"
        return JSONResponse(
            status_code=500,
            content={"error": message},
        )

    # ── Routes ─────────────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(analysis_router)
    app.include_router(qa_router)
    app.include_router(compare_router)
    app.include_router(research_router)

    # ── Static Files ───────────────────────────────────────────────────────
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Serve Frontend ─────────────────────────────────────────────────────
    template_dir = Path(__file__).parent / "templates"

    # Cache the HTML content and its ETag at module level for efficiency
    _html_cache: dict[str, tuple[str, str]] = {}

    @app.get("/", response_class=HTMLResponse)
    async def serve_frontend(request: Request):
        """Serve the main application page with ETag support."""
        index_path = template_dir / "index.html"
        if not index_path.exists():
            return HTMLResponse(
                content="<h1>LegalLens</h1><p>Frontend template not found.</p>",
                status_code=200,
            )

        # Check cache / recompute ETag
        cache_key = str(index_path)
        mtime = index_path.stat().st_mtime
        mtime_key = f"{mtime}"
        if cache_key not in _html_cache or _html_cache[cache_key][1] != mtime_key:
            content = index_path.read_text(encoding="utf-8")
            etag = hashlib.md5(content.encode()).hexdigest()  # noqa: S324
            _html_cache[cache_key] = (content, mtime_key)
        else:
            content = _html_cache[cache_key][0]
            etag = hashlib.md5(content.encode()).hexdigest()  # noqa: S324

        # ETag conditional response (304 Not Modified)
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match.strip('"') == etag:
            return HTMLResponse(content="", status_code=304, headers={"ETag": f'"{etag}"'})

        return HTMLResponse(
            content=content,
            headers={"ETag": f'"{etag}"'},
        )

    return app


app = create_app()
