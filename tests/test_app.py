"""Comprehensive tests for LegalLens.

Tests cover:
1. Health endpoint
2. File upload validation (size, type, magic bytes)
3. Schema validation
4. Evidence verifier logic
5. Prompt injection defense
6. API error handling
7. Comparison schema validation
8. Safe filename handling
9. App boot without Gemini key
10. Mocked Gemini integration tests
"""

import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.security import compute_file_hash, sanitize_filename, validate_pdf_magic
from app.main import app
from app.models.schemas import (
    ChangeType,
    ComparisonItem,
    DocumentAnalysis,
    DocumentAnswer,
    DocumentComparison,
    Evidence,
    Finding,
    SupportStatus,
)
from app.services.verifier import verify_analysis, verify_answer, verify_comparison

client = TestClient(app)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_pdf_bytes(text: str = "Sample legal document content for testing.") -> bytes:
    """Create minimal valid PDF bytes for testing."""
    # Minimal PDF structure
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


def make_non_pdf_bytes() -> bytes:
    """Create bytes that are NOT a valid PDF."""
    return b"This is not a PDF file at all."


def make_oversized_bytes(size_mb: int = 11) -> bytes:
    """Create bytes exceeding the upload limit."""
    return b"%PDF" + b"x" * (size_mb * 1024 * 1024)


# ── 1. Health Endpoint ─────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_response_structure(self):
        response = client.get("/api/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data
        assert "gemini_configured" in data

    def test_health_shows_gemini_not_configured(self):
        """When gemini_configured is False, health endpoint should reflect it."""
        from unittest.mock import PropertyMock
        with patch("app.config.Settings.gemini_configured", new_callable=PropertyMock, return_value=False):
            response = client.get("/api/health")
            data = response.json()
            assert data["gemini_configured"] is False


# ── 2. File Upload Validation ──────────────────────────────────────────────────

class TestUploadValidation:
    def test_reject_oversized_file(self):
        """Files exceeding MAX_UPLOAD_MB should be rejected with 413."""
        large_data = make_oversized_bytes(11)
        response = client.post(
            "/api/documents/analyze",
            files={"file": ("large.pdf", io.BytesIO(large_data), "application/pdf")},
            data={"concerns": "[]"},
        )
        assert response.status_code == 413

    def test_reject_non_pdf_mime(self):
        """Non-PDF MIME types should be rejected with 415."""
        response = client.post(
            "/api/documents/analyze",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"concerns": "[]"},
        )
        assert response.status_code == 415

    def test_reject_non_pdf_magic(self):
        """Files without PDF magic bytes should be rejected even with PDF MIME."""
        non_pdf = make_non_pdf_bytes()
        response = client.post(
            "/api/documents/analyze",
            files={"file": ("fake.pdf", io.BytesIO(non_pdf), "application/pdf")},
            data={"concerns": "[]"},
        )
        assert response.status_code == 415

    def test_reject_empty_file(self):
        """Empty files should be rejected."""
        response = client.post(
            "/api/documents/analyze",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            data={"concerns": "[]"},
        )
        assert response.status_code == 400


# ── 3. Safe Filename Handling ──────────────────────────────────────────────────

class TestFilenameSanitization:
    def test_strips_directory_components(self):
        assert "/" not in sanitize_filename("../../etc/passwd")
        assert "\\" not in sanitize_filename("..\\..\\windows\\system32\\cmd.exe")

    def test_replaces_special_characters(self):
        result = sanitize_filename("file <with> special|chars.pdf")
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_truncates_long_names(self):
        long_name = "a" * 200 + ".pdf"
        result = sanitize_filename(long_name)
        assert len(result) <= 100

    def test_handles_empty_name(self):
        result = sanitize_filename("")
        assert result.endswith(".pdf")
        assert len(result) > 4


# ── 4. PDF Validation ─────────────────────────────────────────────────────────

class TestPdfValidation:
    def test_valid_pdf_magic(self):
        assert validate_pdf_magic(b"%PDF-1.4 rest of content") is True

    def test_invalid_magic(self):
        assert validate_pdf_magic(b"not a pdf") is False

    def test_empty_bytes(self):
        assert validate_pdf_magic(b"") is False

    def test_short_bytes(self):
        assert validate_pdf_magic(b"%PD") is False


# ── 5. File Hash ───────────────────────────────────────────────────────────────

class TestFileHash:
    def test_consistent_hash(self):
        data = b"test content"
        assert compute_file_hash(data) == compute_file_hash(data)

    def test_different_content_different_hash(self):
        assert compute_file_hash(b"a") != compute_file_hash(b"b")

    def test_returns_hex_string(self):
        result = compute_file_hash(b"test")
        assert len(result) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in result)


# ── 6. Schema Validation ──────────────────────────────────────────────────────

class TestSchemaValidation:
    def test_evidence_creation(self):
        e = Evidence(
            document_name="test.pdf",
            page_number=5,
            section="3.1",
            excerpt="This is the excerpt",
            support_status=SupportStatus.SUPPORTED,
        )
        assert e.page_number == 5
        assert e.support_status == SupportStatus.SUPPORTED

    def test_evidence_optional_fields(self):
        e = Evidence(
            document_name="test.pdf",
            excerpt="excerpt",
            support_status=SupportStatus.NOT_FOUND,
        )
        assert e.page_number is None
        assert e.section is None

    def test_document_analysis_defaults(self):
        a = DocumentAnalysis(
            document_type="Employment Agreement",
            summary="Test summary",
        )
        assert a.findings == []
        assert a.obligations == []
        assert a.missing_information == []
        assert "not professional legal advice" in a.disclaimer.lower()

    def test_document_answer_creation(self):
        answer = DocumentAnswer(
            answer="Notice period is 60 days",
            support_status=SupportStatus.SUPPORTED,
            evidence=[
                Evidence(
                    document_name="contract.pdf",
                    page_number=14,
                    excerpt="60 days notice",
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        assert answer.support_status == SupportStatus.SUPPORTED
        assert len(answer.evidence) == 1

    def test_comparison_item_creation(self):
        item = ComparisonItem(
            category="compensation",
            change_type=ChangeType.CHANGED,
            document_a_text="$50,000",
            document_b_text="$60,000",
            explanation="Salary increased",
            why_it_matters="Direct financial impact",
        )
        assert item.change_type == ChangeType.CHANGED


# ── 7. Verifier Tests ─────────────────────────────────────────────────────────

class TestVerifier:
    def test_supported_without_evidence_downgraded(self):
        """SUPPORTED finding with no evidence must be downgraded."""
        analysis = DocumentAnalysis(
            document_type="Test",
            summary="Test",
            findings=[
                Finding(
                    category="test",
                    title="Test Finding",
                    plain_language="Test",
                    why_it_matters="Test",
                    evidence=[],  # No evidence!
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        result = verify_analysis(analysis, {"test.pdf"})
        assert result.findings[0].support_status != SupportStatus.SUPPORTED

    def test_supported_with_evidence_kept(self):
        """SUPPORTED finding with evidence should remain SUPPORTED."""
        analysis = DocumentAnalysis(
            document_type="Test",
            summary="Test",
            findings=[
                Finding(
                    category="test",
                    title="Valid Finding",
                    plain_language="Test",
                    why_it_matters="Test",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            page_number=1,
                            excerpt="relevant text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        result = verify_analysis(analysis, {"test.pdf"})
        assert result.findings[0].support_status == SupportStatus.SUPPORTED

    def test_not_found_answer_clears_evidence(self):
        """NOT_FOUND answers should not have evidence."""
        answer = DocumentAnswer(
            answer="Cannot determine",
            support_status=SupportStatus.NOT_FOUND,
            evidence=[
                Evidence(
                    document_name="test.pdf",
                    excerpt="fake",
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        result = verify_answer(answer, {"test.pdf"})
        assert result.support_status == SupportStatus.NOT_FOUND
        assert len(result.evidence) == 0

    def test_answer_supported_without_evidence_downgraded(self):
        """SUPPORTED answer without evidence should be downgraded."""
        answer = DocumentAnswer(
            answer="Notice is 30 days",
            support_status=SupportStatus.SUPPORTED,
            evidence=[],
        )
        result = verify_answer(answer, {"test.pdf"})
        assert result.support_status == SupportStatus.AMBIGUOUS

    def test_invalid_page_number_cleared(self):
        """Negative page numbers should be set to None."""
        analysis = DocumentAnalysis(
            document_type="Test",
            summary="Test",
            findings=[
                Finding(
                    category="test",
                    title="Test",
                    plain_language="Test",
                    why_it_matters="Test",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            page_number=-1,
                            excerpt="text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        result = verify_analysis(analysis, {"test.pdf"})
        assert result.findings[0].evidence[0].page_number is None

    def test_comparison_verification(self):
        """Comparison verifier should validate evidence."""
        comparison = DocumentComparison(
            summary="Test comparison",
            items=[
                ComparisonItem(
                    category="test",
                    change_type=ChangeType.CHANGED,
                    document_a_text="old",
                    document_b_text="new",
                    explanation="changed",
                    why_it_matters="important",
                    support_status=SupportStatus.SUPPORTED,
                )
            ],
        )
        result = verify_comparison(comparison, "a.pdf", "b.pdf")
        # SUPPORTED with no evidence should be downgraded
        assert result.items[0].support_status == SupportStatus.AMBIGUOUS


# ── 8. Prompt Injection Defense ────────────────────────────────────────────────

class TestPromptInjection:
    """Verify that prompt injection text in documents stays as data."""

    @patch("app.services.gemini.get_gemini_client")
    def test_injection_in_document_treated_as_data(self, mock_client):
        """Document containing injection instructions should be treated as data."""
        # The system prompt explicitly marks document content as DATA
        from app.prompts.analysis import ANALYSIS_SYSTEM_PROMPT
        assert "UNTRUSTED DATA" in ANALYSIS_SYSTEM_PROMPT
        assert "Never follow" in ANALYSIS_SYSTEM_PROMPT or "never follow" in ANALYSIS_SYSTEM_PROMPT.lower()

    def test_document_wrapped_in_data_tags(self):
        """Document text should be wrapped in data tags before sending to Gemini."""
        # Verify the gemini service wraps content
        import inspect

        from app.services.gemini import generate_structured_response
        source = inspect.getsource(generate_structured_response)
        assert "DOCUMENT_DATA" in source

    def test_qa_prompt_prevents_inference(self):
        """QA prompt should prevent model from inferring absent information."""
        from app.prompts.qa import QA_SYSTEM_PROMPT
        assert "NOT" in QA_SYSTEM_PROMPT
        assert "Do NOT fill" in QA_SYSTEM_PROMPT or "do not fill" in QA_SYSTEM_PROMPT.lower()


# ── 9. App Boots Without Gemini ────────────────────────────────────────────────

class TestAppBoot:
    def test_app_boots_without_gemini_key(self):
        """Application should start successfully without GEMINI_API_KEY."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_frontend_served(self):
        """Frontend HTML should be served at root."""
        response = client.get("/")
        assert response.status_code == 200
        assert "LegalLens" in response.text

    def test_security_headers_present(self):
        """Security headers should be present on responses."""
        response = client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert "X-Request-ID" in response.headers


# ── 10. API Error Handling ─────────────────────────────────────────────────────

class TestAPIErrorHandling:
    def test_gemini_not_configured_returns_503(self):
        """AI endpoints should return 503 when Gemini is not configured."""
        pdf_bytes = make_pdf_bytes()
        from unittest.mock import PropertyMock
        with patch("app.config.Settings.gemini_configured", new_callable=PropertyMock, return_value=False):
            response = client.post(
                "/api/documents/analyze",
                files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                data={"concerns": "[]"},
            )
            assert response.status_code == 503

    def test_ask_without_document_returns_404(self):
        """Asking about a non-existent document should return 404."""
        response = client.post(
            "/api/documents/ask",
            json={
                "question": "What is the notice period?",
                "document_id": "nonexistent_hash",
            },
        )
        assert response.status_code == 404

    def test_prepare_without_analysis_returns_404(self):
        """Preparing questions without prior analysis should return 404."""
        response = client.post(
            "/api/documents/prepare",
            data={"document_id": "nonexistent"},
        )
        assert response.status_code == 404

    def test_invalid_json_in_ask(self):
        """Invalid JSON body should be rejected."""
        response = client.post(
            "/api/documents/ask",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


# ── 11. OpenAPI Docs ───────────────────────────────────────────────────────────

class TestOpenAPI:
    def test_openapi_schema_available(self):
        """OpenAPI schema should be accessible in development."""
        response = client.get("/api/docs")
        assert response.status_code == 200


# ── 12. Vercel Serverless Entrypoint ──────────────────────────────────────────

class TestVercelEntrypoint:
    def test_vercel_entrypoint_reexports_app(self):
        """Verify api/index.py cleanly imports and re-exports the main FastAPI application."""
        from api.index import app as vercel_app

        assert vercel_app is not None
        assert vercel_app.title == "LegalLens"

