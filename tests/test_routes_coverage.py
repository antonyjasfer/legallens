"""Tests specifically targeting remaining coverage gaps in routes and services.

Covers:
- app/dependencies.py (get_app_settings)
- app/api/routes_qa.py (cached doc, file search grounded QA, error cases)
- app/api/routes_compare.py (comparison endpoint, concerns handling, error cases)
- app/api/routes_analysis.py (delete endpoint, cache retrieval paths)
- app/services/legal_context.py (research_legal_context)
- app/main.py (ETag 304 response, Cache-Control headers)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes_analysis import _analysis_cache, _document_cache, get_cached_document
from app.core.errors import GeminiAPIError, GeminiNotConfiguredError
from app.dependencies import get_app_settings
from app.main import app
from app.models.schemas import (
    DocumentAnswer,
    Evidence,
    LegalContextResult,
    SupportStatus,
)
from app.services.document_processor import PageContent, ProcessedDocument

client = TestClient(app)


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


def test_dependencies_get_app_settings():
    """Test get_app_settings dependency provider."""
    settings = get_app_settings()
    assert settings is not None
    assert hasattr(settings, "gemini_model")


def test_main_etag_304_and_cache_control():
    """Test frontend ETag cache reuse without MD5 recalculation, 304, and static cache semantics."""
    from app.main import _html_cache

    # First request populates cache
    res1 = client.get("/")
    assert res1.status_code == 200
    etag = res1.headers.get("etag")
    assert etag is not None
    assert len(_html_cache) > 0

    # Second request reuses cached entry without recalculating MD5
    with patch("hashlib.md5") as mock_md5:
        res2 = client.get("/", headers={"if-none-match": etag})
        assert res2.status_code == 304
        mock_md5.assert_not_called()

    # Static CSS cache-control header has max-age but does NOT claim immutable
    res_css = client.get("/static/css/app.css")
    assert res_css.status_code == 200
    cache_ctrl = res_css.headers.get("cache-control", "")
    assert "public, max-age=" in cache_ctrl
    assert "immutable" not in cache_ctrl


def test_accessibility_semantics_and_css():
    """Verify accessibility semantics in frontend and CSS rules."""
    from pathlib import Path

    js_code = (Path(__file__).parent.parent / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css_code = (Path(__file__).parent.parent / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    # 1. Language selector has a valid accessible group label and role="group"
    assert 'role="group"' in js_code
    assert 'aria-labelledby="language-label"' in js_code
    assert 'id="language-label"' in js_code

    # 2. Language buttons expose selected state via aria-pressed
    assert 'aria-pressed="${AppState.language === \'en\'' in js_code
    assert "aria-pressed" in js_code

    # 3. Upload keyboard handler supports Enter and Space
    assert "handleUploadKeydown" in js_code
    assert 'event.key === "Enter" || event.key === " "' in js_code

    # 4. Focus visible rules exist
    assert ":focus-visible" in css_code
    assert ".upload-area:focus-visible" in css_code

    # 5. Reduced motion preferences honored
    assert "prefers-reduced-motion" in css_code


@pytest.mark.asyncio
async def test_legal_context_research():
    """Test external legal context research service."""
    from app.services.legal_context import research_legal_context

    mock_gemini_res = {
        "context": "Governing laws require clear disclosure.",
        "citations": [
            {
                "title": "Contract Law Guidelines",
                "url": "https://example.com/law",
                "snippet": "Relevant legal code overview.",
            }
        ],
    }

    with patch(
        "app.services.legal_context.generate_with_search_grounding",
        new_callable=AsyncMock,
        return_value=mock_gemini_res,
    ):
        result = await research_legal_context("What are termination notice rules?", "California")
        assert isinstance(result, LegalContextResult)
        assert result.context == "Governing laws require clear disclosure."
        assert len(result.citations) == 1
        assert result.citations[0].title == "Contract Law Guidelines"


def test_routes_qa_successful_standard():
    """Test asking a question about a cached document using standard extractor."""
    doc_id = "test-doc-qa-std"
    doc = ProcessedDocument(
        filename="contract.pdf",
        total_pages=1,
        pages=[PageContent(page_number=1, text="Termination notice is 30 days.")],
        full_text="Termination notice is 30 days.",
        metadata={},
    )
    _document_cache[doc_id] = doc

    expected_answer = DocumentAnswer(
        answer="Notice period is 30 days.",
        support_status=SupportStatus.SUPPORTED,
        evidence=[
            Evidence(
                excerpt="Termination notice is 30 days.",
                support_status=SupportStatus.SUPPORTED,
                page_number=1,
                document_name="contract.pdf",
            )
        ],
        suggested_questions=["What is the penalty for early termination?"],
    )

    with patch(
        "app.api.routes_qa.ask_document", new_callable=AsyncMock, return_value=expected_answer
    ):
        res = client.post(
            "/api/documents/ask",
            json={"document_id": doc_id, "question": "What is the notice period?"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "answer" in data
        assert data["answer"]["answer"] == "Notice period is 30 days."


def test_routes_qa_file_search_branch():
    """Test QA route when document has file_search_document_name indexed."""
    doc_id = "test-doc-qa-fs"
    doc = ProcessedDocument(
        filename="cloud_contract.pdf",
        total_pages=1,
        pages=[PageContent(page_number=1, text="Payment is due within 15 days.")],
        full_text="Payment is due within 15 days.",
        metadata={"file_search_document_name": "files/test1234"},
    )
    _document_cache[doc_id] = doc

    mock_query_res = MagicMock()
    mock_query_res.answer_text = "Payment is due within 15 days."
    mock_query_res.support_status = SupportStatus.SUPPORTED
    mock_query_res.evidence = [
        Evidence(
            excerpt="Payment is due within 15 days.",
            support_status=SupportStatus.SUPPORTED,
            page_number=1,
            document_name="cloud_contract.pdf",
        )
    ]

    mock_fs_svc = MagicMock()
    mock_fs_svc.settings.gemini_configured = True
    mock_fs_svc.async_query_indexed_document = AsyncMock(return_value=mock_query_res)

    with patch("app.services.file_search.FileSearchService", return_value=mock_fs_svc):
        res = client.post(
            "/api/documents/ask", json={"document_id": doc_id, "question": "When is payment due?"}
        )
        assert res.status_code == 200
        assert res.json()["answer"]["support_status"] == "SUPPORTED"


def test_routes_qa_errors():
    """Test QA route error propagation: not configured (503) and API error (502)."""
    doc_id = "test-doc-qa-err"
    _document_cache[doc_id] = ProcessedDocument(
        filename="err.pdf", total_pages=1, pages=[], full_text="test", metadata={}
    )

    with patch(
        "app.api.routes_qa.ask_document",
        new_callable=AsyncMock,
        side_effect=GeminiNotConfiguredError(),
    ):
        res1 = client.post("/api/documents/ask", json={"document_id": doc_id, "question": "test?"})
        assert res1.status_code == 503

    with patch(
        "app.api.routes_qa.ask_document",
        new_callable=AsyncMock,
        side_effect=GeminiAPIError("API failed"),
    ):
        res2 = client.post("/api/documents/ask", json={"document_id": doc_id, "question": "test?"})
        assert res2.status_code == 502


def test_routes_compare_success_and_concerns():
    """Test comparing two PDF documents successfully with parsed concerns."""
    mock_comparison = MagicMock()
    mock_comparison.model_dump.return_value = {
        "differences": [],
        "overall_summary": "No critical changes found.",
        "risk_level": "LOW",
    }

    pdf_a = make_pdf_bytes("First contract content.")
    pdf_b = make_pdf_bytes("Second contract content with alterations.")

    with patch(
        "app.api.routes_compare.compare_documents",
        new_callable=AsyncMock,
        return_value=mock_comparison,
    ):
        # Case 1: valid JSON concerns list
        res1 = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_a, "application/pdf"),
                "file_b": ("docB.pdf", pdf_b, "application/pdf"),
            },
            data={"concerns": json.dumps(["indemnity", "termination"]), "language": "en"},
        )
        assert res1.status_code == 200
        assert "comparison" in res1.json()

        # Case 2: invalid JSON concerns string (falls back to empty list)
        res2 = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_a, "application/pdf"),
                "file_b": ("docB.pdf", pdf_b, "application/pdf"),
            },
            data={"concerns": "{not-valid-json", "language": "en"},
        )
        assert res2.status_code == 200

        # Case 3: valid JSON but not a list (e.g. an integer)
        res3 = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_a, "application/pdf"),
                "file_b": ("docB.pdf", pdf_b, "application/pdf"),
            },
            data={"concerns": "123", "language": "en"},
        )
        assert res3.status_code == 200


def test_routes_compare_errors():
    """Test comparison endpoint errors (503, 502, 422)."""
    pdf_bytes = make_pdf_bytes("Valid contract text for errors testing.")

    with patch(
        "app.api.routes_compare.compare_documents",
        new_callable=AsyncMock,
        side_effect=GeminiNotConfiguredError(),
    ):
        res = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_bytes, "application/pdf"),
                "file_b": ("docB.pdf", pdf_bytes, "application/pdf"),
            },
        )
        assert res.status_code == 503

    with patch(
        "app.api.routes_compare.compare_documents",
        new_callable=AsyncMock,
        side_effect=GeminiAPIError("API error"),
    ):
        res = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_bytes, "application/pdf"),
                "file_b": ("docB.pdf", pdf_bytes, "application/pdf"),
            },
        )
        assert res.status_code == 502

    with patch(
        "app.api.routes_compare.extract_text_from_pdf", side_effect=ValueError("Corrupt PDF")
    ):
        res = client.post(
            "/api/documents/compare",
            files={
                "file_a": ("docA.pdf", pdf_bytes, "application/pdf"),
                "file_b": ("docB.pdf", pdf_bytes, "application/pdf"),
            },
        )
        assert res.status_code == 422


def test_routes_analysis_delete_endpoint(tmp_path):
    """Test DELETE /api/documents/{document_id} endpoint cleans up all services."""
    doc_id = "test-doc-to-delete"
    doc = ProcessedDocument(
        filename="to_delete.pdf",
        total_pages=1,
        pages=[],
        full_text="",
        metadata={"file_search_document_name": "files/del123", "session_id": "sess-del"},
    )
    _document_cache[doc_id] = doc
    _analysis_cache[doc_id] = {}

    with (
        patch("app.services.gcs.GCSService.get_instance") as mock_gcs_cls,
        patch("app.services.firestore.FirestoreService.get_instance") as mock_fs_cls,
        patch("app.services.file_search.FileSearchService") as mock_search_cls,
    ):
        mock_gcs = mock_gcs_cls.return_value
        mock_gcs.delete_document.return_value = True

        mock_fs = mock_fs_cls.return_value
        mock_fs.delete_document_metadata.return_value = True

        mock_search = mock_search_cls.return_value
        mock_search.delete_indexed_file.return_value = True

        res = client.delete(f"/api/documents/{doc_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "deleted"
        assert "cloud_storage" in data["cleaned_services"]
        assert "file_search" in data["cleaned_services"]
        assert "firestore" in data["cleaned_services"]
        assert "local_cache" in data["cleaned_services"]
        assert doc_id not in _document_cache


def test_get_cached_document_disk_and_gemini_fallback(tmp_path):
    """Test get_cached_document fallback to disk cache and Gemini list."""
    doc_id = "cached-doc-fallback"

    # Disk cache test
    disk_data = {
        "filename": "disk.pdf",
        "total_pages": 1,
        "full_text": "Sample text",
        "pages": [{"page_number": 1, "text": "Sample text", "char_count": 11}],
        "metadata": {},
    }
    with patch("app.api.routes_analysis.get_settings") as mock_settings:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{doc_id}.json").write_text(json.dumps(disk_data), encoding="utf-8")
        mock_settings.return_value.upload_dir = tmp_path
        mock_settings.return_value.gemini_configured = False

        _document_cache.pop(doc_id, None)
        loaded = get_cached_document(doc_id)
        assert loaded is not None
        assert loaded.filename == "disk.pdf"

    # Gemini Files list fallback test
    gemini_doc_id = "unique-gemini-doc-id-12345"
    _document_cache.pop(gemini_doc_id, None)

    mock_file = MagicMock()
    mock_file.name = "files/gemini123"
    mock_file.display_name = f"legallens__{gemini_doc_id[:16]}__contract.pdf"

    mock_fs_svc = MagicMock()
    mock_client = MagicMock()
    mock_client.files.list.return_value = [mock_file]
    mock_fs_svc._get_client.return_value = mock_client

    with (
        patch("app.api.routes_analysis.get_settings") as mock_settings,
        patch("app.services.file_search.FileSearchService", return_value=mock_fs_svc),
    ):
        mock_settings.return_value.upload_dir = tmp_path
        mock_settings.return_value.gemini_configured = True

        found = get_cached_document(gemini_doc_id)
        assert found is not None
        assert "contract.pdf" in found.filename
        assert found.metadata.get("file_search_document_name") == "files/gemini123"
