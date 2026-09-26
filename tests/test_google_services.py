"""Unit tests for Google Cloud and Gemini services integration.

All external Google APIs (Gemini, GCS, Firestore, Document AI) are strictly MOCKED
to prevent network dependency or API quota consumption.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app.main import app
from app.models.schemas import SupportStatus
from app.services.document_ai import DocumentAIService
from app.services.file_search import FileSearchService
from app.services.firestore import FirestoreService
from app.services.gcs import GCSService
from app.services.gemini import _sanitize_error_for_user

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Gemini Error Conversion & Sanitization
# ---------------------------------------------------------------------------

class TestGeminiErrorConversion:
    """Verify raw Google API exceptions are translated into safe, friendly messages."""

    def test_leaked_key_sanitization(self):
        err = errors.ClientError(403, {"error": {"message": "Your API key was reported as leaked"}})
        msg = _sanitize_error_for_user(err)
        assert "compromised" in msg.lower() or "update gemini_api_key" in msg.lower()
        assert "AIzaSy" not in msg

    def test_quota_exceeded_sanitization(self):
        err = errors.ClientError(429, {"error": {"message": "Resource has been exhausted"}})
        msg = _sanitize_error_for_user(err)
        assert "quota" in msg.lower()

    def test_service_unavailable_sanitization(self):
        err = errors.ServerError(503, {"error": {"message": "The model is overloaded. Please try again later."}})
        msg = _sanitize_error_for_user(err)
        assert "high demand" in msg.lower() or "temporary error" in msg.lower()


# ---------------------------------------------------------------------------
# 2. Google Cloud Storage (GCS) Service
# ---------------------------------------------------------------------------

class TestGCSService:
    """Verify GCS PDF validation, server-controlled pathing, and fallback."""

    def test_pdf_validation_rejects_non_pdf(self):
        from app.core.errors import InvalidFileTypeError
        gcs = GCSService.get_instance()
        with pytest.raises(InvalidFileTypeError):
            gcs.upload_document(
                content=b"not a pdf content",
                original_filename="bad.txt",
                session_id="sess-123",
                document_id="doc-456",
            )

    def test_server_controlled_naming_with_mock_gcs(self):
        gcs = GCSService.get_instance()
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client.bucket.return_value = mock_bucket
        gcs._client = mock_client

        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        result = gcs.upload_document(
            content=pdf_bytes,
            original_filename="../../../evil_path.pdf",
            session_id="sess-safe",
            document_id="doc-unique-hash",
        )
        assert result["blob_path"] == "legal-documents/sess-safe/doc-unique-hash.pdf"
        assert result["storage_backend"] == "gcs"
        mock_bucket.blob.assert_called_once_with("legal-documents/sess-safe/doc-unique-hash.pdf")

    def test_cleanup_deletes_file_with_mock_gcs(self):
        gcs = GCSService.get_instance()
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_bucket.blob.return_value = mock_blob
        mock_client.bucket.return_value = mock_bucket
        gcs._client = mock_client

        deleted = gcs.delete_document(
            blob_path="legal-documents/sess-del/doc-del.pdf",
            session_id="sess-del",
            document_id="doc-del",
        )
        assert deleted is True
        mock_blob.delete.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Firestore Metadata Repository
# ---------------------------------------------------------------------------

class TestFirestoreRepository:
    """Verify metadata storage and clean local memory fallback."""

    def test_save_and_retrieve_document_metadata(self):
        fs = FirestoreService.get_instance()
        doc_id = "test-doc-metadata-id"
        fs.save_document_metadata({
            "document_id": doc_id,
            "session_id": "sess-test",
            "original_filename": "contract.pdf",
            "gcs_object": "legal-documents/sess-test/test-doc-metadata-id.pdf",
            "sha256": "abc123sha",
            "mime_type": "application/pdf",
            "file_search_document_name": "files/testfile123",
        })

        retrieved = fs.get_document_metadata(doc_id)
        assert retrieved is not None
        assert retrieved["document_id"] == doc_id
        assert retrieved["original_filename"] == "contract.pdf"
        assert retrieved["file_search_document_name"] == "files/testfile123"

        # Verify no raw contract text is stored
        assert "full_text" not in retrieved
        assert "raw_content" not in retrieved

    def test_delete_metadata(self):
        fs = FirestoreService.get_instance()
        doc_id = "test-doc-del-id"
        fs.save_document_metadata({
            "document_id": doc_id,
            "session_id": "sess-del",
            "original_filename": "contract.pdf",
            "gcs_object": "legal-documents/contract.pdf",
            "sha256": "sha",
            "mime_type": "application/pdf",
        })
        assert fs.get_document_metadata(doc_id) is not None
        deleted = fs.delete_document_metadata(doc_id)
        assert deleted is True
        assert fs.get_document_metadata(doc_id) is None


# ---------------------------------------------------------------------------
# 4. Gemini File Search Service & Citation Parsing
# ---------------------------------------------------------------------------

class TestFileSearchCitationParsing:
    """Verify deterministic extraction of citations from model answers."""

    def test_extract_citations_from_sections_and_quotes(self):
        svc = FileSearchService()
        sample_answer = (
            "According to the agreement, either party may terminate at-will. "
            "[Page 2, Section 5.1: 'Employment is at-will. Either party may terminate at any time.']\n"
            "Also, Section 5.3: 'Upon termination without Cause by Employer, Employee shall receive two months base salary.'"
        )

        evidence = svc._extract_evidence_from_response(sample_answer, "employment.pdf")
        assert len(evidence) >= 2

        # Check first citation
        ev1 = evidence[0]
        assert ev1.document_name == "employment.pdf"
        assert ev1.page_number == 2
        assert ev1.section == "5.1"
        assert "Employment is at-will" in ev1.excerpt

    def test_not_found_produces_exact_disclaimer(self):
        svc = FileSearchService()
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test-not-found"
        mock_client.files.get.return_value = mock_file

        mock_resp = MagicMock()
        mock_resp.text = "This cannot be determined from the document you provided."
        mock_client.models.generate_content.return_value = mock_resp

        svc._client = mock_client
        result = svc.query_indexed_document(
            file_name="files/test-not-found",
            question="What is the employee stock grant schedule?",
            document_display_name="test.pdf",
        )

        assert result.support_status == SupportStatus.NOT_FOUND
        assert result.answer_text == "This cannot be determined from the document you provided."
        assert len(result.evidence) == 0


# ---------------------------------------------------------------------------
# 5. Document AI Layout Parser Fallback
# ---------------------------------------------------------------------------

class TestDocumentAIFallback:
    """Verify text quality evaluation and graceful fallback when Document AI is unconfigured."""

    def test_evaluate_needs_document_ai(self):
        doc_ai = DocumentAIService()
        # Scanned document with 0 text
        assert doc_ai.evaluate_needs_document_ai(total_pages=5, extracted_chars=0) is True
        # Very low density
        assert doc_ai.evaluate_needs_document_ai(total_pages=2, extracted_chars=50) is True
        # Normal text PDF (e.g. 5000 chars over 3 pages)
        assert doc_ai.evaluate_needs_document_ai(total_pages=3, extracted_chars=5000) is False

    def test_unconfigured_document_ai_returns_safe_result(self):
        doc_ai = DocumentAIService()
        doc_ai.settings.document_ai_enabled = False
        res = doc_ai.parse_layout(file_bytes=b"%PDF-1.4...")
        assert res.success is False
        assert "not configured" in (res.error_message or "").lower()


# ---------------------------------------------------------------------------
# 6. Google Health Endpoint
# ---------------------------------------------------------------------------

class TestGoogleHealthEndpoint:
    """Verify /api/health/google returns sanitized status for all Google services."""

    def test_google_health_response_keys_and_no_secrets(self):
        response = client.get("/api/health/google")
        assert response.status_code == 200
        data = response.json()

        for svc_key in ("gemini", "file_search", "cloud_storage", "firestore", "document_ai"):
            assert svc_key in data
            assert "configured" in data[svc_key]
            assert "reachable" in data[svc_key]

        # Verify no credentials leaked
        text_body = response.text
        assert "AIza" not in text_body
        assert "private_key" not in text_body
        assert "secret" not in text_body


# ---------------------------------------------------------------------------
# 7. External Legal Context (Search Grounding) Separation
# ---------------------------------------------------------------------------

class TestLegalContextSeparation:
    """Verify external research does not mix with uploaded document Q&A."""

    def test_research_endpoint_structure(self):
        with patch(
            "app.api.routes_research.research_legal_context",
            return_value=MagicMock(
                model_dump=lambda: {
                    "query": "notice periods in India",
                    "context": "General Indian law requires notice as specified in employment contracts.",
                    "citations": [{"title": "Ministry of Labour", "url": "https://labour.gov.in", "snippet": "Notice rules"}],
                }
            ),
        ):
            resp = client.post("/api/legal-context", json={"query": "notice periods in India", "jurisdiction": "India"})
            assert resp.status_code == 200
            result = resp.json()["result"]
            assert "General Indian law" in result["context"]
            assert len(result["citations"]) == 1
            assert result["citations"][0]["url"] == "https://labour.gov.in"


# ---------------------------------------------------------------------------
# 8. Privacy Cleanup Behavior
# ---------------------------------------------------------------------------

class TestPrivacyCleanup:
    """Verify document deletion removes data across all storage layers."""

    def test_delete_endpoint_cleans_resources(self):
        doc_id = "test-privacy-cleanup-id"
        from app.api.routes_analysis import _analysis_cache, _document_cache
        from app.services.document_processor import ProcessedDocument
        _document_cache[doc_id] = ProcessedDocument(
            filename="confidential.pdf",
            total_pages=1,
            pages=[],
            full_text="sensitive text",
            metadata={"session_id": "sess-del", "gcs_object": "legal-documents/sess-del/test-privacy-cleanup-id.pdf"},
        )
        _analysis_cache[doc_id] = MagicMock()

        resp = client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert doc_id not in _document_cache
        assert doc_id not in _analysis_cache
