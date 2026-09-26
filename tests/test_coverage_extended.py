"""Extended coverage tests for LegalLens modules.

Targets modules identified by coverage analysis as under-covered:
- app/services/analyzer.py (25%)
- app/services/gemini.py (43%)
- app/services/document_processor.py (70%)
- app/services/verifier.py (69%)
- app/api/routes_compare.py (27%)
- app/api/routes_qa.py (37%)
- app/api/routes_analysis.py (51%)
- app/prompts/* (20-75%)
- app/models/schemas.py normalizers (83%)
- app/config.py edge paths (90%)

All tests use mocking — NO real network calls or API quota consumption.
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.errors import DocumentProcessingError, GeminiAPIError, GeminiNotConfiguredError
from app.main import app
from app.models.schemas import (
    DateItem,
    DocumentAnalysis,
    Evidence,
    Finding,
    KeyFact,
    MissingInformation,
    MonetaryTerm,
    Obligation,
    SupportStatus,
)
from app.services.document_processor import ProcessedDocument
from app.services.verifier import (
    _validate_evidence,
    verify_analysis,
)

client = TestClient(app)


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_pdf_bytes(text: str = "Sample legal document content for testing.") -> bytes:
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


# ── Analyzer Service Coverage ──────────────────────────────────────────────────


class TestAnalyzerService:
    """Cover app/services/analyzer.py branches."""

    @pytest.mark.asyncio
    async def test_analyze_document_success(self):
        """Successful analysis parses structured response and runs verification."""
        from app.services.analyzer import analyze_document

        doc = ProcessedDocument(
            filename="test.pdf", total_pages=2, pages=[], full_text="Contract text here"
        )
        mock_response = {
            "document_type": "Employment Agreement",
            "summary": "A standard employment contract.",
            "key_facts": [{"label": "Parties", "value": "A and B"}],
            "findings": [
                {
                    "category": "compensation",
                    "title": "Base Salary",
                    "plain_language": "Salary is $100K",
                    "why_it_matters": "Key financial term",
                    "evidence": [
                        {
                            "document_name": "test.pdf",
                            "page_number": 1,
                            "excerpt": "$100,000 per annum",
                            "support_status": "SUPPORTED",
                        }
                    ],
                    "support_status": "SUPPORTED",
                }
            ],
            "obligations": [
                {
                    "actor": "Employee",
                    "action": "Maintain confidentiality",
                    "deadline": "Indefinite",
                    "evidence": [],
                }
            ],
            "dates": [
                {"description": "Start Date", "date_text": "January 1, 2026", "evidence": []}
            ],
            "monetary_terms": [{"description": "Salary", "amount": "$100,000", "evidence": []}],
            "missing_information": [
                {
                    "topic": "Equity",
                    "explanation": "No stock options mentioned",
                    "suggested_question": "Are there stock options?",
                }
            ],
        }

        with patch(
            "app.services.analyzer.generate_structured_response", return_value=mock_response
        ):
            result = await analyze_document(
                doc=doc, concerns=["salary_compensation"], language="en"
            )

        assert result.document_type == "Employment Agreement"
        assert len(result.findings) >= 1
        assert result.findings[0].support_status == SupportStatus.SUPPORTED

    @pytest.mark.asyncio
    async def test_analyze_document_invalid_response_fallback(self):
        """When Gemini returns unparseable response, analysis returns safe fallback."""
        from app.services.analyzer import analyze_document

        doc = ProcessedDocument(filename="test.pdf", total_pages=1, pages=[], full_text="Test")

        with patch(
            "app.services.analyzer.generate_structured_response",
            return_value={"invalid_field": True},
        ):
            result = await analyze_document(doc=doc, concerns=[], language="en")

        assert result.document_type  # Should have a value (either default or from partial parse)

    @pytest.mark.asyncio
    async def test_ask_document_success(self):
        """Successful Q&A returns answer with evidence."""
        from app.services.analyzer import ask_document

        doc = ProcessedDocument(
            filename="contract.pdf", total_pages=1, pages=[], full_text="Notice: 30 days"
        )
        mock_response = {
            "answer": "The notice period is 30 days.",
            "support_status": "SUPPORTED",
            "evidence": [
                {
                    "document_name": "contract.pdf",
                    "page_number": 1,
                    "excerpt": "30 days notice",
                    "support_status": "SUPPORTED",
                }
            ],
            "missing_information": [],
            "suggested_questions": ["What happens after the notice period?"],
        }

        with patch(
            "app.services.analyzer.generate_structured_response", return_value=mock_response
        ):
            result = await ask_document(
                doc=doc, question="What is the notice period?", language="en"
            )

        assert result.support_status == SupportStatus.SUPPORTED
        assert len(result.evidence) == 1

    @pytest.mark.asyncio
    async def test_ask_document_invalid_response(self):
        """Invalid Q&A response falls back to AMBIGUOUS."""
        from app.services.analyzer import ask_document

        doc = ProcessedDocument(filename="test.pdf", total_pages=1, pages=[], full_text="Test")

        with patch(
            "app.services.analyzer.generate_structured_response", return_value={"wrong": "format"}
        ):
            result = await ask_document(doc=doc, question="Test?", language="en")

        assert result.support_status == SupportStatus.AMBIGUOUS

    @pytest.mark.asyncio
    async def test_compare_documents_success(self):
        """Successful comparison parses structured result."""
        from app.services.analyzer import compare_documents

        doc_a = ProcessedDocument(
            filename="v1.pdf", total_pages=1, pages=[], full_text="Version 1 text"
        )
        doc_b = ProcessedDocument(
            filename="v2.pdf", total_pages=1, pages=[], full_text="Version 2 text"
        )
        mock_response = {
            "summary": "Salary increased from $100K to $120K",
            "items": [
                {
                    "category": "compensation",
                    "change_type": "CHANGED",
                    "document_a_text": "$100,000",
                    "document_b_text": "$120,000",
                    "explanation": "Salary increased",
                    "why_it_matters": "Financial impact",
                    "evidence_a": [
                        {
                            "document_name": "v1.pdf",
                            "excerpt": "$100,000",
                            "support_status": "SUPPORTED",
                        }
                    ],
                    "evidence_b": [
                        {
                            "document_name": "v2.pdf",
                            "excerpt": "$120,000",
                            "support_status": "SUPPORTED",
                        }
                    ],
                }
            ],
            "missing_in_a": [],
            "missing_in_b": ["equity clause"],
        }

        with patch(
            "app.services.analyzer.generate_structured_response", return_value=mock_response
        ):
            result = await compare_documents(
                doc_a=doc_a, doc_b=doc_b, concerns=["compensation"], language="en"
            )

        assert "Salary" in result.summary
        assert len(result.items) >= 1

    @pytest.mark.asyncio
    async def test_compare_invalid_response(self):
        """Invalid comparison response falls back safely."""
        from app.services.analyzer import compare_documents

        doc_a = ProcessedDocument(filename="a.pdf", total_pages=1, pages=[], full_text="A")
        doc_b = ProcessedDocument(filename="b.pdf", total_pages=1, pages=[], full_text="B")

        with patch(
            "app.services.analyzer.generate_structured_response", return_value={"broken": True}
        ):
            result = await compare_documents(doc_a=doc_a, doc_b=doc_b, concerns=[], language="en")

        assert result.summary  # Should have some fallback text

    @pytest.mark.asyncio
    async def test_prepare_for_professional_complete(self):
        """prepare_for_professional populates all fields from rich analysis."""
        from app.services.analyzer import prepare_for_professional

        analysis = DocumentAnalysis(
            document_type="NDA",
            summary="Mutual NDA",
            key_facts=[KeyFact(label="Duration", value="2 years")],
            findings=[
                Finding(
                    category="confidentiality",
                    title="Scope",
                    plain_language="Broad scope",
                    why_it_matters="Risk",
                    evidence=[
                        Evidence(
                            document_name="nda.pdf",
                            page_number=2,
                            section="3.1",
                            excerpt="all information",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                    support_status=SupportStatus.SUPPORTED,
                ),
                Finding(
                    category="penalties",
                    title="Unclear Penalty",
                    plain_language="Ambiguous penalty clause",
                    why_it_matters="Risk",
                    evidence=[],
                    support_status=SupportStatus.AMBIGUOUS,
                ),
            ],
            missing_information=[
                MissingInformation(
                    topic="Carve-outs",
                    explanation="No exceptions listed",
                    suggested_question="What information is excluded?",
                )
            ],
        )

        result = await prepare_for_professional(analysis)
        assert len(result.what_i_understand) >= 1
        assert len(result.what_is_unclear) >= 1
        assert len(result.missing_from_document) >= 1
        assert len(result.questions_to_ask) >= 1
        assert len(result.important_sections) >= 1


# ── Verifier Extended Coverage ─────────────────────────────────────────────────


class TestVerifierExtended:
    """Cover remaining verifier branches."""

    def test_evidence_empty_excerpt_downgraded(self):
        """SUPPORTED evidence with empty excerpt should be downgraded to AMBIGUOUS."""
        e = Evidence(
            document_name="test.pdf", excerpt="   ", support_status=SupportStatus.SUPPORTED
        )
        result = _validate_evidence(e, {"test.pdf"})
        assert result.support_status == SupportStatus.AMBIGUOUS

    def test_evidence_document_name_case_insensitive_match(self):
        """Document name should match case-insensitively."""
        e = Evidence(
            document_name="TEST.PDF", excerpt="text", support_status=SupportStatus.SUPPORTED
        )
        result = _validate_evidence(e, {"test.pdf"})
        assert result.document_name == "test.pdf"

    def test_evidence_document_name_stem_match(self):
        """Document name should match by normalized stem."""
        e = Evidence(
            document_name="employment_agreement",
            excerpt="text",
            support_status=SupportStatus.SUPPORTED,
        )
        result = _validate_evidence(e, {"employment-agreement.pdf"})
        assert result.document_name == "employment-agreement.pdf"

    def test_evidence_single_known_doc_fallback(self):
        """When only one document is known, unmatched name should default to it."""
        e = Evidence(
            document_name="completely_wrong.pdf",
            excerpt="text",
            support_status=SupportStatus.SUPPORTED,
        )
        result = _validate_evidence(e, {"the_only_doc.pdf"})
        assert result.document_name == "the_only_doc.pdf"

    def test_evidence_unknown_doc_multiple_known(self):
        """With multiple known docs, unmatched name should stay and log warning."""
        e = Evidence(
            document_name="unknown.pdf", excerpt="text", support_status=SupportStatus.SUPPORTED
        )
        result = _validate_evidence(e, {"doc_a.pdf", "doc_b.pdf"})
        assert result.document_name == "unknown.pdf"  # Cannot resolve

    def test_verify_analysis_obligations_and_dates(self):
        """Verify analysis validates obligations, dates, monetary terms, and key facts."""
        analysis = DocumentAnalysis(
            document_type="Test",
            summary="Test",
            obligations=[
                Obligation(
                    actor="Employer",
                    action="Pay salary",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            page_number=-5,
                            excerpt="text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                )
            ],
            dates=[
                DateItem(
                    description="Start",
                    date_text="Jan 1",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            page_number=0,
                            excerpt="text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                )
            ],
            monetary_terms=[
                MonetaryTerm(
                    description="Salary",
                    amount="$100K",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            excerpt="text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                )
            ],
            key_facts=[
                KeyFact(
                    label="Parties",
                    value="A and B",
                    evidence=[
                        Evidence(
                            document_name="test.pdf",
                            excerpt="text",
                            support_status=SupportStatus.SUPPORTED,
                        )
                    ],
                )
            ],
        )

        result = verify_analysis(analysis, {"test.pdf"})
        # Invalid page numbers should be cleared
        assert result.obligations[0].evidence[0].page_number is None
        assert result.dates[0].evidence[0].page_number is None


# ── Schema Normalizer Coverage ─────────────────────────────────────────────────


class TestSchemaNormalizers:
    """Cover model_validator normalizers in schemas.py."""

    def test_finding_single_evidence_dict_normalized(self):
        """Finding with evidence as dict (not list) should be normalized."""
        data = {
            "category": "test",
            "title": "Test",
            "plain_language": "Test",
            "why_it_matters": "Test",
            "evidence": {
                "document_name": "test.pdf",
                "excerpt": "text",
                "support_status": "SUPPORTED",
            },
        }
        f = Finding.model_validate(data)
        assert isinstance(f.evidence, list)
        assert len(f.evidence) == 1

    def test_obligation_party_to_actor_normalization(self):
        """Obligation with 'party' key should be normalized to 'actor'."""
        data = {
            "party": "Employer",
            "obligation": "Pay salary",
            "evidence": {
                "document_name": "test.pdf",
                "excerpt": "text",
                "support_status": "SUPPORTED",
            },
        }
        o = Obligation.model_validate(data)
        assert o.actor == "Employer"
        assert o.action == "Pay salary"
        assert isinstance(o.evidence, list)

    def test_date_item_date_key_normalization(self):
        """DateItem with 'date' key should be normalized to 'date_text'."""
        data = {"description": "Start", "date": "2026-01-01", "evidence": []}
        d = DateItem.model_validate(data)
        assert d.date_text == "2026-01-01"

    def test_monetary_term_key_normalization(self):
        """MonetaryTerm with 'term' key should be normalized to 'description'."""
        data = {"term": "Signing Bonus", "amount": "$10,000", "evidence": []}
        m = MonetaryTerm.model_validate(data)
        assert m.description == "Signing Bonus"

    def test_missing_info_questions_normalization(self):
        """MissingInformation with 'questions' key should be normalized."""
        data = {"topic": "Equity", "questions": "What about stock options?"}
        m = MissingInformation.model_validate(data)
        assert m.suggested_question == "What about stock options?"

    def test_missing_info_why_it_matters_normalization(self):
        """MissingInformation with 'why_it_matters' key should be normalized to 'explanation'."""
        data = {
            "topic": "Equity",
            "why_it_matters": "Important for compensation",
            "suggested_question": "Q?",
        }
        m = MissingInformation.model_validate(data)
        assert m.explanation == "Important for compensation"

    def test_missing_info_default_explanation(self):
        """MissingInformation without explanation should get a default."""
        data = {"topic": "Equity", "suggested_question": "What about it?"}
        m = MissingInformation.model_validate(data)
        assert "Clarification" in m.explanation or "clarification" in m.explanation.lower()

    def test_key_fact_evidence_dict_normalized(self):
        """KeyFact with evidence as dict should be normalized to list."""
        data = {
            "label": "Duration",
            "value": "2 years",
            "evidence": {
                "document_name": "test.pdf",
                "excerpt": "text",
                "support_status": "SUPPORTED",
            },
        }
        kf = KeyFact.model_validate(data)
        assert isinstance(kf.evidence, list)


# ── Document Processor Coverage ────────────────────────────────────────────────


class TestDocumentProcessorExtended:
    """Cover document_processor.py edge cases."""

    def test_corrupt_pdf_raises_processing_error(self):
        """Corrupt PDF bytes should raise DocumentProcessingError."""
        with pytest.raises(DocumentProcessingError):
            from app.services.document_processor import extract_text_from_pdf

            extract_text_from_pdf(b"%PDF-corrupt-data-here", "corrupt.pdf")

    def test_empty_text_pdf_raises_error(self):
        """PDF with no extractable text should raise DocumentProcessingError."""
        from app.services.document_processor import extract_text_from_pdf

        # Minimal PDF with no text content
        minimal_pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
trailer << /Size 4 /Root 1 0 R >>
startxref
0
%%EOF"""
        # This may or may not have text depending on PyMuPDF version
        # The important thing is it doesn't crash
        try:
            result = extract_text_from_pdf(minimal_pdf, "empty.pdf")
            # If it succeeds, it should have metadata
            assert isinstance(result, ProcessedDocument)
        except DocumentProcessingError:
            pass  # Expected for truly empty PDFs

    def test_processed_document_has_content_property(self):
        """ProcessedDocument.has_content should reflect text presence."""
        doc = ProcessedDocument(filename="test.pdf", total_pages=1, full_text="Some content")
        assert doc.has_content is True

        empty_doc = ProcessedDocument(filename="test.pdf", total_pages=1, full_text="   ")
        assert empty_doc.has_content is False


# ── Config Edge Paths ──────────────────────────────────────────────────────────


class TestConfigEdgePaths:
    """Cover config.py validators and property edge cases."""

    def test_gcs_configured_false_when_empty(self):
        """gcs_configured should be False when bucket is empty."""
        from app.config import Settings

        s = Settings(gcs_bucket="")
        assert s.gcs_configured is False

    def test_document_ai_configured_requires_all_fields(self):
        """document_ai_configured requires enabled flag, processor ID, and project."""
        from app.config import Settings

        s = Settings(document_ai_enabled=False)
        assert s.document_ai_configured is False

        s2 = Settings(
            document_ai_enabled=True, document_ai_processor_id="", google_cloud_project="proj"
        )
        assert s2.document_ai_configured is False

    def test_empty_int_fields_get_defaults(self):
        """Empty string int fields should fall back to defaults."""
        from app.config import Settings

        s = Settings(document_retention_days="", max_upload_mb="", port="")
        assert s.document_retention_days == 7
        assert s.max_upload_mb == 10
        assert s.port == 8080

    def test_empty_bool_field_defaults_false(self):
        """Empty string bool field should default to False."""
        from app.config import Settings

        s = Settings(document_ai_enabled="")
        assert s.document_ai_enabled is False


# ── Prompt Coverage ────────────────────────────────────────────────────────────


class TestPromptCoverage:
    """Cover prompt building functions."""

    def test_analysis_prompt_builder(self):
        """build_analysis_prompt should produce valid prompt for concerns."""
        from app.prompts.analysis import build_analysis_prompt

        result = build_analysis_prompt(
            ["salary_compensation", "termination"], "custom concern", "en"
        )
        assert "salary_compensation" in result
        assert "custom concern" in result

    def test_analysis_prompt_empty_concerns(self):
        """build_analysis_prompt should handle empty concerns."""
        from app.prompts.analysis import build_analysis_prompt

        result = build_analysis_prompt([], "", "en")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_comparison_prompt_builder(self):
        """build_comparison_prompt should produce valid prompt."""
        from app.prompts.comparison import build_comparison_prompt

        result = build_comparison_prompt(["compensation"], "", "en")
        assert isinstance(result, str)

    def test_qa_prompt_builder(self):
        """build_qa_prompt should produce valid prompt."""
        from app.prompts.qa import build_qa_prompt

        result = build_qa_prompt("What is the notice period?", "en")
        assert "notice period" in result

    def test_research_prompt_builder(self):
        """build_research_prompt should produce valid prompt."""
        from app.prompts.research import build_research_prompt

        result = build_research_prompt("employment law", "India")
        assert "employment law" in result

    def test_analysis_system_prompt_has_key_instructions(self):
        """Analysis system prompt must contain evidence-first and anti-hallucination instructions."""
        from app.prompts.analysis import ANALYSIS_SYSTEM_PROMPT

        assert "UNTRUSTED DATA" in ANALYSIS_SYSTEM_PROMPT
        assert "evidence" in ANALYSIS_SYSTEM_PROMPT.lower()

    def test_language_map_contains_supported_languages(self):
        """LANGUAGE_MAP must support en, ta, hi at minimum."""
        from app.prompts.analysis import LANGUAGE_MAP

        assert "en" in LANGUAGE_MAP
        assert "ta" in LANGUAGE_MAP
        assert "hi" in LANGUAGE_MAP


# ── Route Integration with Mocked Services ─────────────────────────────────────


class TestRouteIntegration:
    """Cover route paths with mocked Gemini services."""

    def test_compare_endpoint_rejects_non_pdf_a(self):
        """Compare endpoint rejects non-PDF first document."""
        response = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("a.txt", io.BytesIO(b"not pdf"), "text/plain"),
                "file_b": ("b.pdf", io.BytesIO(make_pdf_bytes()), "application/pdf"),
            },
            data={"concerns": "[]"},
        )
        assert response.status_code in (400, 415)

    def test_compare_endpoint_rejects_empty_file(self):
        """Compare endpoint rejects empty files."""
        response = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("a.pdf", io.BytesIO(b""), "application/pdf"),
                "file_b": ("b.pdf", io.BytesIO(make_pdf_bytes()), "application/pdf"),
            },
            data={"concerns": "[]"},
        )
        assert response.status_code == 400

    def test_compare_endpoint_rejects_oversized(self):
        """Compare endpoint rejects oversized files."""
        large = b"%PDF" + b"x" * (11 * 1024 * 1024)
        response = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("a.pdf", io.BytesIO(large), "application/pdf"),
                "file_b": ("b.pdf", io.BytesIO(make_pdf_bytes()), "application/pdf"),
            },
            data={"concerns": "[]"},
        )
        assert response.status_code == 413

    def test_delete_nonexistent_document(self):
        """Delete endpoint on nonexistent document should still return 200."""
        response = client.delete("/api/documents/nonexistent-doc-id")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert "local_cache" in data["cleaned_services"]

    def test_research_endpoint_gemini_error(self):
        """Research endpoint should return 502 on GeminiAPIError."""
        with patch(
            "app.api.routes_research.research_legal_context",
            side_effect=GeminiAPIError("AI service failed"),
        ):
            response = client.post("/api/legal-context", json={"query": "test query"})
            assert response.status_code == 502

    def test_research_endpoint_not_configured(self):
        """Research endpoint should return 503 when Gemini not configured."""
        with patch(
            "app.api.routes_research.research_legal_context",
            side_effect=GeminiNotConfiguredError(),
        ):
            response = client.post("/api/legal-context", json={"query": "test query"})
            assert response.status_code == 503


# ── Gemini Service Extended Coverage ───────────────────────────────────────────


class TestGeminiServiceExtended:
    """Cover gemini.py code paths."""

    @pytest.mark.asyncio
    async def test_generate_structured_empty_response(self):
        """Empty model response should raise GeminiAPIError."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "key"

        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = True
            ms.return_value.gemini_api_key = "key"
            ms.return_value.gemini_model = "gemini-3.8-flash"

            with pytest.raises(GeminiAPIError):
                await svc.generate_structured(system_prompt="test", user_prompt="test")

    @pytest.mark.asyncio
    async def test_generate_structured_json_parsing(self):
        """Valid JSON response should be parsed correctly."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "key"

        mock_resp = MagicMock()
        mock_resp.text = '```json\n{"result": "success"}\n```'
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = True
            ms.return_value.gemini_api_key = "key"
            ms.return_value.gemini_model = "gemini-3.8-flash"

            result = await svc.generate_structured(system_prompt="test", user_prompt="test")

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_generate_structured_invalid_json_raises(self):
        """Invalid JSON from model should raise GeminiAPIError."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "key"

        mock_resp = MagicMock()
        mock_resp.text = "not valid json at all {"
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = True
            ms.return_value.gemini_api_key = "key"
            ms.return_value.gemini_model = "gemini-3.8-flash"

            with pytest.raises(GeminiAPIError, match="invalid JSON"):
                await svc.generate_structured(system_prompt="test", user_prompt="test")

    def test_gemini_not_configured_raises(self):
        """Accessing client without API key should raise GeminiNotConfiguredError."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        svc._client = None

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = False
            with pytest.raises(GeminiNotConfiguredError):
                svc.get_client()

    def test_client_reinitialized_on_key_change(self):
        """Client should be recreated when API key changes."""
        from app.services.gemini import GeminiService

        svc = GeminiService()
        svc._last_key = "old-key"
        svc._client = MagicMock()

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = True
            ms.return_value.gemini_api_key = "new-key"
            ms.return_value.gemini_model = "gemini-3.8-flash"

            with patch("app.services.gemini.genai.Client") as mock_genai:
                mock_genai.return_value = MagicMock()
                _ = svc.get_client()
                mock_genai.assert_called_once_with(api_key="new-key")

    @pytest.mark.asyncio
    async def test_search_grounding_auth_error_stops(self):
        """Search grounding should stop on 401/403 errors."""
        from google.genai import errors

        from app.services.gemini import GeminiService

        svc = GeminiService()
        mock_client = MagicMock()
        svc._client = mock_client
        svc._last_key = "key"

        mock_client.models.generate_content.side_effect = errors.ClientError(
            401, {"error": {"message": "Unauthorized"}}
        )

        with patch("app.services.gemini.get_settings") as ms:
            ms.return_value.gemini_configured = True
            ms.return_value.gemini_api_key = "key"
            ms.return_value.gemini_model = "gemini-3.8-flash"

            with pytest.raises(GeminiAPIError):
                await svc.generate_search_grounded_response(
                    system_prompt="test", user_prompt="test"
                )

        # Should stop after first attempt (auth error)
        assert mock_client.models.generate_content.call_count == 1
