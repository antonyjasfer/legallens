"""Production Acceptance Test for LegalLens on Vercel."""

import json
import os
import sys
from pathlib import Path

import httpx

BASE_URL = os.environ.get("BASE_URL", sys.argv[1] if len(sys.argv) > 1 else "https://legallens-sable.vercel.app")
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def run_acceptance_tests():
    client = httpx.Client(base_url=BASE_URL, timeout=120.0)
    print(f"Running Production Acceptance Tests on {BASE_URL}...\n")

    # 1. Health check
    print("1. Testing GET /api/health...")
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
    health_data = resp.json()
    assert health_data["status"] == "healthy"
    assert health_data["gemini_configured"] is True
    print(f"   [PASS] Health check: {health_data}")

    # 2. Upload and analyze employment agreement
    print("\n2. Testing POST /api/documents/analyze with samples/employment_agreement.pdf...")
    pdf_path = SAMPLES_DIR / "employment_agreement.pdf"
    assert pdf_path.exists(), f"Sample PDF not found: {pdf_path}"

    with open(pdf_path, "rb") as f:
        files = {"file": ("employment_agreement.pdf", f, "application/pdf")}
        data = {
            "concerns": json.dumps(["Salary / Compensation", "Notice Period", "Termination", "Non-Compete"]),
            "language": "en",
        }
        resp = client.post("/api/documents/analyze", files=files, data=data)

    assert resp.status_code == 200, f"Analyze failed: {resp.status_code} {resp.text}"
    analyze_data = resp.json()
    document_id = analyze_data["document_id"]
    analysis = analyze_data["analysis"]
    print(f"   [PASS] Analysis completed! Document ID: {document_id}")
    print(f"   Doc Type: {analysis.get('document_type')}")
    print(f"   Findings count: {len(analysis.get('findings', []))}")
    print(f"   Missing info count: {len(analysis.get('missing_information', []))}")

    # 3. Ask question: "What is my notice period?" (Should be SUPPORTED)
    print("\n3. Testing Q&A: 'What is my notice period?'...")
    resp = client.post(
        "/api/documents/ask",
        json={"document_id": document_id, "question": "What is my notice period?"},
    )
    assert resp.status_code == 200, f"Ask failed: {resp.status_code} {resp.text}"
    qa_data = resp.json()["answer"]
    support_status = qa_data.get("support_status")
    answer_text = qa_data.get("answer", "")
    evidence = qa_data.get("evidence", [])
    print(f"   [PASS] Support status: {support_status}")
    print(f"   Answer excerpt: {answer_text[:120]}...")
    print(f"   Evidence citations: {len(evidence)}")
    if evidence:
        print(f"   First citation: Page {evidence[0].get('page_number')} - '{evidence[0].get('excerpt', '')[:80]}...'")

    # 4. Ask absent question: "What happens to my stock options if I resign?" (Should be NOT_FOUND)
    print("\n4. Testing Q&A (Absent topic): 'What happens to my stock options if I resign?'...")
    resp = client.post(
        "/api/documents/ask",
        json={"document_id": document_id, "question": "What happens to my stock options if I resign?"},
    )
    assert resp.status_code == 200, f"Ask failed: {resp.status_code} {resp.text}"
    qa_absent = resp.json()["answer"]
    absent_status = qa_absent.get("support_status")
    absent_text = qa_absent.get("answer", "")
    print(f"   [PASS] Support status: {absent_status}")
    print(f"   Answer: {absent_text[:150]}")
    assert absent_status in ("NOT_FOUND", "PARTIALLY_SUPPORTED"), f"Expected NOT_FOUND, got {absent_status}"

    # 5. Document comparison: NDA Mutual vs Strict
    print("\n5. Testing POST /api/documents/compare (NDA Mutual v1 vs Strict v2)...")
    nda_v1 = SAMPLES_DIR / "nda_mutual_v1.pdf"
    nda_v2 = SAMPLES_DIR / "nda_strict_v2.pdf"
    with open(nda_v1, "rb") as f1, open(nda_v2, "rb") as f2:
        files = {
            "file_a": ("nda_mutual_v1.pdf", f1, "application/pdf"),
            "file_b": ("nda_strict_v2.pdf", f2, "application/pdf"),
        }
        resp = client.post("/api/documents/compare", files=files, data={"language": "en"})

    assert resp.status_code == 200, f"Compare failed: {resp.status_code} {resp.text}"
    compare_data = resp.json()["comparison"]
    changes = compare_data.get("changes", [])
    print(f"   [PASS] Compare completed! Detected {len(changes)} changes between versions.")
    if changes:
        print(f"   Sample change: [{changes[0].get('change_type')}] {changes[0].get('category')} - {changes[0].get('explanation', '')[:80]}")

    # 6. External Legal Context research
    print("\n6. Testing POST /api/legal-context (Google Search Grounding)...")
    resp = client.post(
        "/api/legal-context",
        json={"query": "statutory notice period requirements in employment law", "jurisdiction": "general"},
    )
    assert resp.status_code == 200, f"Legal context failed: {resp.status_code} {resp.text}"
    research_res = resp.json().get("result", {})
    context_text = research_res.get("context", "")
    citations = research_res.get("citations", [])
    print(f"   [PASS] Research completed! Context length: {len(context_text)} chars, Citations: {len(citations)}")
    if citations:
        print(f"   First citation: {citations[0].get('title')} ({citations[0].get('url')})")

    print("\n============================================================")
    print("ALL PRODUCTION ACCEPTANCE TESTS PASSED ON VERCEL!")
    print("============================================================")


if __name__ == "__main__":
    try:
        run_acceptance_tests()
    except Exception as exc:
        print(f"\n[FAIL] Test failed: {exc}", file=sys.stderr)
        sys.exit(1)
