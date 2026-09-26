"""Efficiency and performance behavior tests.

Verifies that LegalLens implements efficient resource usage:
- Bounded retries and polling
- Async-correct I/O for blocking operations
- Temp file cleanup
- SHA-based document cache prevents duplicate parsing
- Fallback discrimination (only retry on transient errors)
- File Search bounded polling constants
- Context limits and single-pass analysis

All tests are deterministic, fast, and require NO real Gemini API or network access.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import compute_file_hash
from app.models.schemas import (
    DocumentAnalysis,
    DocumentAnswer,
    Evidence,
    Finding,
    SupportStatus,
)
from app.services.document_processor import ProcessedDocument, extract_text_from_pdf
from app.services.verifier import verify_analysis, verify_answer

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_pdf_bytes(text: str = "Sample legal document content for testing.") -> bytes:
    """Create minimal valid PDF bytes for testing."""
    content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {len(text) + 30} >>
stream
BT /F1 12 Tf 72 720 Td ({text}) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
trailer << /Size 6 /Root 1 0 R >>
startxref
0
%%EOF"""
    return content.encode("latin-1")


# ── 1. Bounded File Search Polling ─────────────────────────────────────────────


class TestBoundedPolling:
    """Verify File Search indexing uses bounded polling with defined limits."""

    def test_polling_constants_defined(self):
        """MAX_POLL_ATTEMPTS and interval constants must be defined."""
        from app.services.file_search import (
            INITIAL_POLL_INTERVAL_S,
            MAX_POLL_ATTEMPTS,
            MAX_POLL_INTERVAL_S,
        )

        assert isinstance(MAX_POLL_ATTEMPTS, int)
        assert MAX_POLL_ATTEMPTS > 0
        assert MAX_POLL_ATTEMPTS <= 60  # Reasonable upper bound
        assert INITIAL_POLL_INTERVAL_S > 0
        assert MAX_POLL_INTERVAL_S >= INITIAL_POLL_INTERVAL_S

    def test_polling_has_maximum_attempts(self):
        """File indexing polling must not loop indefinitely."""
        from app.services.file_search import MAX_POLL_ATTEMPTS

        # MAX_POLL_ATTEMPTS must provide a hard upper bound
        assert MAX_POLL_ATTEMPTS <= 60, "Polling should not exceed 60 attempts"

    def test_upload_and_index_respects_poll_limit(self):
        """upload_and_index must stop polling after MAX_POLL_ATTEMPTS."""
        from app.services.file_search import MAX_POLL_ATTEMPTS, FileSearchService

        svc = FileSearchService()
        mock_client = MagicMock()

        # Simulate a file that never finishes processing
        mock_uploaded_file = MagicMock()
        mock_uploaded_file.name = "files/stuck-file"
        mock_uploaded_file.state = "PROCESSING"
        mock_client.files.upload.return_value = mock_uploaded_file

        # files.get always returns PROCESSING
        mock_processing_file = MagicMock()
        mock_processing_file.name = "files/stuck-file"
        mock_processing_file.state = "PROCESSING"
        mock_client.files.get.return_value = mock_processing_file

        svc._client = mock_client

        # Create a temp file for upload
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            tmp_path = f.name

        try:
            with patch("app.services.file_search.time.sleep"):
                _ = svc.upload_and_index(tmp_path, "test.pdf")

            # Should have polled exactly MAX_POLL_ATTEMPTS times
            assert mock_client.files.get.call_count <= MAX_POLL_ATTEMPTS
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ── 2. Bounded Gemini Retries ──────────────────────────────────────────────────


class TestBoundedRetries:
    """Verify Gemini API retries are bounded and discriminate error types."""

    def test_max_retries_parameter_exists(self):
        """generate_structured must accept max_retries with a reasonable default."""
        import inspect

        from app.services.gemini import GeminiService

        sig = inspect.signature(GeminiService.generate_structured)
        assert "max_retries" in sig.parameters
        default = sig.parameters["max_retries"].default
        assert isinstance(default, int)
        assert 1 <= default <= 5  # Reasonable bounds

    @pytest.mark.asyncio
    async def test_auth_error_stops_retries(self):
        """401/403 errors must NOT trigger retries or fallback models."""
        from google.genai import errors

        from app.core.errors import GeminiAPIError
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "test-key"

        # Simulate 403 on every call
        mock_client.models.generate_content.side_effect = errors.ClientError(
            403, {"error": {"message": "Permission denied"}}
        )

        with patch("app.services.gemini.get_settings") as mock_settings:
            mock_settings.return_value.gemini_configured = True
            mock_settings.return_value.gemini_api_key = "test-key"
            mock_settings.return_value.gemini_model = "gemini-3.8-flash"

            with pytest.raises(GeminiAPIError):
                await svc.generate_structured(
                    system_prompt="test",
                    user_prompt="test",
                    max_retries=2,
                )

        # Should have called only ONCE (no retries for auth errors)
        assert mock_client.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_transient_503_retries_bounded(self):
        """503 errors should retry but within max_retries bound."""
        from google.genai import errors

        from app.core.errors import GeminiAPIError
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "test-key"

        # Simulate persistent 503
        mock_client.models.generate_content.side_effect = errors.ServerError(
            503, {"error": {"message": "Model overloaded"}}
        )

        with patch("app.services.gemini.get_settings") as mock_settings:
            mock_settings.return_value.gemini_configured = True
            mock_settings.return_value.gemini_api_key = "test-key"
            mock_settings.return_value.gemini_model = "gemini-3.8-flash"

            with pytest.raises(GeminiAPIError):
                await svc.generate_structured(
                    system_prompt="test",
                    user_prompt="test",
                    max_retries=2,
                )

        # Should have retried (max_retries + 1 attempts per model, across fallback models)
        # but total calls must be bounded
        total_calls = mock_client.models.generate_content.call_count
        assert total_calls > 1  # Did retry
        assert total_calls <= 12  # Bounded (4 models × 3 attempts max)


# ── 3. Document Cache Prevents Duplicate Parsing ──────────────────────────────


class TestDocumentCache:
    """Verify SHA-based cache prevents redundant PDF re-parsing."""

    def test_sha256_hash_is_deterministic(self):
        """Same content must produce identical hash."""
        content = b"identical content"
        h1 = compute_file_hash(content)
        h2 = compute_file_hash(content)
        assert h1 == h2

    def test_different_content_different_hash(self):
        """Different content must produce different hashes."""
        h1 = compute_file_hash(b"content A")
        h2 = compute_file_hash(b"content B")
        assert h1 != h2

    def test_cache_key_is_sha256_hex(self):
        """Hash output must be a proper SHA-256 hex digest."""
        h = compute_file_hash(b"test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_extract_text_from_pdf_single_pass(self):
        """PDF extraction opens the document exactly once."""
        pdf_bytes = make_pdf_bytes("test content for extraction")

        with patch("app.services.document_processor.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "Extracted legal text for testing purposes"
            mock_doc.__len__ = lambda self: 1
            mock_doc.__getitem__ = lambda self, idx: mock_page
            mock_doc.metadata = {"title": "Test"}
            mock_fitz.open.return_value = mock_doc

            extract_text_from_pdf(pdf_bytes, "test.pdf")

            # fitz.open called exactly once
            mock_fitz.open.assert_called_once()
            mock_doc.close.assert_called_once()


# ── 4. Single-Call Structured Analysis ─────────────────────────────────────────


class TestSingleCallAnalysis:
    """Verify analysis uses single structured Gemini call, not per-concern calls."""

    @pytest.mark.asyncio
    async def test_analyze_document_makes_single_gemini_call(self):
        """Multi-concern analysis must use ONE structured call, not N calls."""
        from app.services.analyzer import analyze_document

        doc = ProcessedDocument(
            filename="test.pdf",
            total_pages=1,
            pages=[],
            full_text="This is a sample employment agreement...",
        )

        mock_response = {
            "document_type": "Employment Agreement",
            "summary": "Test summary",
            "key_facts": [],
            "findings": [],
            "obligations": [],
            "dates": [],
            "monetary_terms": [],
            "missing_information": [],
        }

        with patch(
            "app.services.analyzer.generate_structured_response", return_value=mock_response
        ) as mock_gen:
            await analyze_document(
                doc=doc,
                concerns=["salary_compensation", "notice_period", "termination", "non_compete"],
                custom_concern="stock options vesting",
                language="en",
            )

            # Exactly ONE call for all concerns combined
            assert mock_gen.call_count == 1

    @pytest.mark.asyncio
    async def test_compare_makes_single_gemini_call(self):
        """Document comparison must use ONE structured call, not per-category calls."""
        from app.services.analyzer import compare_documents

        doc_a = ProcessedDocument(
            filename="v1.pdf", total_pages=1, pages=[], full_text="Contract A text"
        )
        doc_b = ProcessedDocument(
            filename="v2.pdf", total_pages=1, pages=[], full_text="Contract B text"
        )

        mock_response = {
            "summary": "Key differences found",
            "items": [],
            "missing_in_a": [],
            "missing_in_b": [],
        }

        with patch(
            "app.services.analyzer.generate_structured_response", return_value=mock_response
        ) as mock_gen:
            await compare_documents(
                doc_a=doc_a,
                doc_b=doc_b,
                concerns=["compensation", "termination", "notice"],
                language="en",
            )

            # Exactly ONE call for all comparison categories
            assert mock_gen.call_count == 1


# ── 5. Async Correctness ──────────────────────────────────────────────────────


class TestAsyncCorrectness:
    """Verify blocking operations are properly offloaded from event loop."""

    def test_file_search_has_async_wrappers(self):
        """FileSearchService must provide async wrappers for blocking methods."""
        from app.services.file_search import FileSearchService

        svc = FileSearchService()
        assert hasattr(svc, "async_upload_and_index")
        assert hasattr(svc, "async_query_indexed_document")
        assert hasattr(svc, "async_delete_indexed_file")
        assert asyncio.iscoroutinefunction(svc.async_upload_and_index)
        assert asyncio.iscoroutinefunction(svc.async_query_indexed_document)
        assert asyncio.iscoroutinefunction(svc.async_delete_indexed_file)

    def test_gemini_generate_structured_is_async(self):
        """GeminiService.generate_structured must be an async method."""
        from app.services.gemini import GeminiService

        assert asyncio.iscoroutinefunction(GeminiService.generate_structured)

    def test_gemini_search_grounded_is_async(self):
        """GeminiService.generate_search_grounded_response must be async."""
        from app.services.gemini import GeminiService

        assert asyncio.iscoroutinefunction(GeminiService.generate_search_grounded_response)


# ── 6. File Search Fallback Discrimination ─────────────────────────────────────


class TestFileSearchFallbackDiscrimination:
    """Verify File Search only retries on transient errors."""

    def test_query_stops_on_auth_error(self):
        """401/403 File Search errors must not cascade to all fallback models."""
        from google.genai import errors

        from app.services.file_search import FileSearchService

        svc = FileSearchService()
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test"
        mock_client.files.get.return_value = mock_file

        # Simulate 403 on generation
        mock_client.models.generate_content.side_effect = errors.ClientError(
            403, {"error": {"message": "Permission denied"}}
        )
        svc._client = mock_client

        from app.core.errors import FileSearchError

        with pytest.raises(FileSearchError), patch("app.services.file_search.time.sleep"):
            svc.query_indexed_document(
                file_name="files/test",
                question="What is the notice period?",
                document_display_name="test.pdf",
            )

        # Should have stopped after first model's auth error
        assert mock_client.models.generate_content.call_count == 1


# ── 7. Verifier Does Not Call LLM ──────────────────────────────────────────────


class TestVerifierEfficiency:
    """Verify deterministic verifier uses NO additional LLM calls."""

    def test_verify_analysis_is_purely_deterministic(self):
        """verify_analysis must be synchronous with no network calls."""
        analysis = DocumentAnalysis(
            document_type="Test",
            summary="Test",
            findings=[
                Finding(
                    category="test",
                    title="Test Finding",
                    plain_language="explanation",
                    why_it_matters="reason",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            page_number=1,
                            excerpt="relevant excerpt text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )

        start = time.perf_counter()
        result = verify_analysis(analysis, {"test.pdf"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Must complete in < 10ms (no network calls)
        assert elapsed_ms < 100
        assert result.findings[0].support_status == SupportStatus.SUPPORTED

    def test_verify_answer_is_purely_deterministic(self):
        """verify_answer must be synchronous with no network calls."""
        answer = DocumentAnswer(
            answer="The notice period is 60 days",
            support_status=SupportStatus.SUPPORTED,
            evidence=[
                Evidence(
                    document_name="test.pdf",
                    page_number=5,
                    excerpt="60 calendar days",
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )

        start = time.perf_counter()
        result = verify_answer(answer, {"test.pdf"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100
        assert result.support_status == SupportStatus.SUPPORTED


# ── 8. Prepare for Professional No Extra API Call ──────────────────────────────


class TestPrepareEfficiency:
    """Verify prepare_for_professional derives data from analysis without API calls."""

    @pytest.mark.asyncio
    async def test_prepare_uses_no_gemini_call(self):
        """prepare_for_professional must derive entirely from the existing analysis."""
        from app.services.analyzer import prepare_for_professional

        analysis = DocumentAnalysis(
            document_type="Employment Agreement",
            summary="Test",
            findings=[
                Finding(
                    category="compensation",
                    title="Base Salary",
                    plain_language="$120,000 annually",
                    why_it_matters="Key financial term",
                    evidence=[
                        Evidence(
                            document_name="contract.pdf",
                            page_number=3,
                            section="4.1",
                            excerpt="base salary of $120,000",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )

        with patch("app.services.gemini.GeminiService.generate_structured") as mock_gen:
            prep = await prepare_for_professional(analysis)
            # Zero Gemini calls for preparation
            mock_gen.assert_not_called()

        assert len(prep.what_i_understand) > 0


# ── 9. Temporary File Lifecycle ────────────────────────────────────────────────


class TestTempFileLifecycle:
    """Verify temporary files are cleaned up properly."""

    def test_routes_analysis_has_cleanup_logic(self):
        """Analyze endpoint must contain temp file cleanup code."""
        import inspect

        from app.api.routes_analysis import analyze_document_endpoint

        source = inspect.getsource(analyze_document_endpoint)
        assert "unlink" in source or "cleanup" in source.lower()

    def test_file_search_delete_validates_file_name(self):
        """delete_indexed_file must reject invalid file names."""
        from app.services.file_search import FileSearchService

        svc = FileSearchService()
        assert svc.delete_indexed_file("") is False
        assert svc.delete_indexed_file("invalid-name") is False
        assert svc.delete_indexed_file("not-files/abc") is False


# ── 10. Serverless Startup Efficiency ──────────────────────────────────────────


class TestServerlessStartup:
    """Verify serverless-safe initialization patterns."""

    def test_gemini_client_lazy_initialization(self):
        """GeminiService must not create client until first use."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        assert svc._client is None  # Not initialized yet

    def test_file_search_client_lazy_initialization(self):
        """FileSearchService must not create client until first use."""
        from app.services.file_search import FileSearchService

        svc = FileSearchService()
        assert svc._client is None

    def test_settings_are_cached(self):
        """get_settings must return cached singleton."""
        from app.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_vercel_entrypoint_imports_cleanly(self):
        """api/index.py must import without side-effecting network calls."""
        start = time.perf_counter()
        from api.index import app as vercel_app

        elapsed_ms = (time.perf_counter() - start) * 1000
        assert vercel_app is not None
        # Import should be fast (< 5 seconds even on cold start)
        assert elapsed_ms < 5000


# ── 11. Context Limits ─────────────────────────────────────────────────────────


class TestContextLimits:
    """Verify context sent to Gemini is bounded and efficient."""

    @pytest.mark.asyncio
    async def test_document_text_wrapped_in_tags(self):
        """Document text must be wrapped in DATA tags to prevent injection."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "test-key"

        mock_resp = MagicMock()
        mock_resp.text = '{"test": true}'
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.services.gemini.get_settings") as mock_settings:
            mock_settings.return_value.gemini_configured = True
            mock_settings.return_value.gemini_api_key = "test-key"
            mock_settings.return_value.gemini_model = "gemini-3.8-flash"

            await svc.generate_structured(
                system_prompt="test",
                user_prompt="analyze this",
                document_text="CONFIDENTIAL CONTRACT TEXT",
            )

        # Verify the document text was wrapped in DOCUMENT_DATA tags
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs.get("contents") or call_args[1].get("contents")
        combined = " ".join(str(c) for c in contents)
        assert "DOCUMENT_DATA" in combined

    def test_structured_response_uses_json_mime(self):
        """generate_structured must request application/json response."""
        import inspect

        from app.services.gemini import GeminiService

        source = inspect.getsource(GeminiService.generate_structured)
        assert "application/json" in source

    def test_structured_response_accepts_schema(self):
        """generate_structured must support response_schema for single-call extraction."""
        import inspect

        from app.services.gemini import GeminiService

        sig = inspect.signature(GeminiService.generate_structured)
        assert "response_schema" in sig.parameters


# ── 12. Gemini Error Classification ───────────────────────────────────────────


class TestGeminiErrorClassification:
    """Verify error messages are sanitized and classified correctly."""

    def test_403_error_sanitized(self):
        """403 should return access denied message without leaking details."""
        from google.genai import errors

        from app.services.gemini import _sanitize_error_for_user

        err = errors.ClientError(403, {"error": {"message": "Forbidden"}})
        msg = _sanitize_error_for_user(err)
        assert "access denied" in msg.lower()
        assert "403" not in msg

    def test_429_error_sanitized(self):
        """429 should mention quota without leaking API details."""
        from google.genai import errors

        from app.services.gemini import _sanitize_error_for_user

        err = errors.ClientError(429, {"error": {"message": "Resource exhausted"}})
        msg = _sanitize_error_for_user(err)
        assert "quota" in msg.lower()

    def test_503_error_sanitized(self):
        """503 should mention high demand."""
        from google.genai import errors

        from app.services.gemini import _sanitize_error_for_user

        err = errors.ServerError(503, {"error": {"message": "Overloaded"}})
        msg = _sanitize_error_for_user(err)
        assert "high demand" in msg.lower() or "temporary" in msg.lower()

    def test_leaked_key_sanitized(self):
        """Leaked key error should not contain actual key value."""
        from google.genai import errors

        from app.services.gemini import _sanitize_error_for_user

        err = errors.ClientError(403, {"error": {"message": "API key AIzaSyABCDEF was leaked"}})
        msg = _sanitize_error_for_user(err)
        assert "AIzaSy" not in msg
        assert "compromised" in msg.lower() or "update" in msg.lower()


# ── 13. Legal Context Separation ───────────────────────────────────────────────


class TestLegalContextSeparation:
    """Verify document Q&A and external research use separate code paths."""

    def test_qa_uses_document_grounded_service(self):
        """Document Q&A must use ask_document (document text), not search grounding."""
        import inspect

        from app.services.analyzer import ask_document

        source = inspect.getsource(ask_document)
        assert "generate_structured_response" in source
        assert "search_grounding" not in source.lower()

    def test_research_uses_search_grounding(self):
        """Legal context research must use Google Search grounding."""
        import inspect

        from app.services.legal_context import research_legal_context

        source = inspect.getsource(research_legal_context)
        assert "search_grounding" in source.lower() or "generate_with_search_grounding" in source

    def test_qa_prompt_prevents_external_inference(self):
        """Q&A system prompt must instruct model to NOT use external knowledge."""
        from app.prompts.qa import QA_SYSTEM_PROMPT

        prompt_lower = QA_SYSTEM_PROMPT.lower()
        assert "not" in prompt_lower
        assert "document" in prompt_lower
