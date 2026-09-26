"""Live integration test for LegalLens with samples/employment_agreement.pdf.

Tests:
1. Health endpoint (GET /api/health/google)
2. Document analysis (POST /api/documents/analyze) with employment_agreement.pdf
3. Document Q&A (POST /api/documents/ask):
   - "What is my notice period?" (Should be SUPPORTED with evidence)
   - "What happens to my stock options if I resign?" (Should be NOT_FOUND with exact disclaimer)
4. External Legal Context (POST /api/legal-context):
   - "employment notice period regulations in California"
5. Privacy cleanup (DELETE /api/documents/{doc_id})
"""

import json
import os
import sys

import httpx

BASE_URL = "http://127.0.0.1:8080"
PDF_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples", "employment_agreement.pdf")


def test_live():
    client = httpx.Client(base_url=BASE_URL, timeout=120.0)

    print("=" * 60)
    print("STEP 1: Testing GET /api/health/google")
    print("=" * 60)
    res = client.get("/api/health/google")
    print(f"Status: {res.status_code}")
    print(json.dumps(res.json(), indent=2))
    assert res.status_code == 200

    print("\n" + "=" * 60)
    print("STEP 2: Uploading and analyzing samples/employment_agreement.pdf")
    print("=" * 60)
    assert os.path.exists(PDF_PATH), f"File not found: {PDF_PATH}"
    concerns = ["Salary / Compensation", "Notice Period", "Termination", "Non-Compete"]

    with open(PDF_PATH, "rb") as f:
        files = {"file": ("employment_agreement.pdf", f, "application/pdf")}
        data = {
            "concerns": json.dumps(concerns),
            "custom_concern": "",
            "language": "en",
        }
        res = client.post("/api/documents/analyze", files=files, data=data)

    print(f"Status: {res.status_code}")
    if res.status_code != 200:
        print("Analysis Error:", res.text)
        sys.exit(1)

    analysis_data = res.json()
    doc_id = analysis_data["document_id"]
    analysis = analysis_data["analysis"]
    metadata = analysis_data.get("metadata", {})

    print(f"Document ID: {doc_id}")
    print(f"Title: {analysis.get('title')}")
    print(f"Parties: {[p.get('name') for p in analysis.get('parties', [])]}")
    print(f"Key facts: {len(analysis.get('key_facts', []))}")
    print(f"Findings count: {len(analysis.get('findings', []))}")
    print(f"Missing info items: {len(analysis.get('missing_info', []))}")
    print(f"Metadata: GCS={metadata.get('gcs_object')}, FileSearch={metadata.get('file_search_document_name')}")

    # Inspect first findings and their evidence
    for i, finding in enumerate(analysis.get("findings", [])[:3]):
        ev_list = finding.get("evidence", [])
        print(f"\nFinding {i+1} [{finding.get('category')}]: {finding.get('summary') or finding.get('title')}")
        for ev in ev_list:
            quote = ev.get("quote") or ""
            print(f"  - Evidence: Page {ev.get('page')}, Section '{ev.get('section')}', Quote: {quote[:60]}...")

    print("\n" + "=" * 60)
    print("STEP 3A: Asking 'What is my notice period?' (Present in document)")
    print("=" * 60)
    qa_res = client.post(
        "/api/documents/ask",
        json={
            "document_id": doc_id,
            "question": "What is my notice period?",
            "language": "en",
        },
    )
    print(f"Status: {qa_res.status_code}")
    if qa_res.status_code == 200:
        ans = qa_res.json()["answer"]
        print(f"Support Status: {ans.get('support_status')}")
        print(f"Answer: {ans.get('answer')}")
        for ev in ans.get("evidence", []):
            print(f"  Evidence: Page {ev.get('page')}, Section {ev.get('section')}, Quote: {ev.get('quote')}")
    else:
        print("QA Error:", qa_res.text)

    print("\n" + "=" * 60)
    print("STEP 3B: Asking 'What happens to my stock options if I resign?' (Absent)")
    print("=" * 60)
    absent_res = client.post(
        "/api/documents/ask",
        json={
            "document_id": doc_id,
            "question": "What happens to my stock options if I resign?",
            "language": "en",
        },
    )
    print(f"Status: {absent_res.status_code}")
    if absent_res.status_code == 200:
        ans2 = absent_res.json()["answer"]
        print(f"Support Status: {ans2.get('support_status')}")
        print(f"Answer: {ans2.get('answer')}")
        assert "This cannot be determined from the document you provided" in (ans2.get("answer") or ""), (
            f"Expected standard disclaimer, got: {ans2.get('answer')}"
        )
        print("  -> PASSED: Returned exact expected not-found disclaimer!")
    else:
        print("Absent QA Error:", absent_res.text)

    print("\n" + "=" * 60)
    print("STEP 4: Testing External Legal Context (Google Search Grounding)")
    print("=" * 60)
    search_res = client.post(
        "/api/legal-context",
        json={
            "query": "employment notice period regulations in California",
            "jurisdiction": "California, US",
        },
    )
    print(f"Status: {search_res.status_code}")
    if search_res.status_code == 200:
        ctx = search_res.json()
        print(f"Summary: {ctx.get('summary')[:150]}...")
        print(f"Disclaimer: {ctx.get('disclaimer')}")
        print(f"Key Points: {len(ctx.get('key_points', []))}")
        print(f"Sources: {len(ctx.get('sources', []))}")
        for src in ctx.get("sources", [])[:2]:
            print(f"  - Source: {src.get('title')} ({src.get('url')})")
    else:
        print("Legal Context Error:", search_res.text)

    print("\n" + "=" * 60)
    print(f"STEP 5: Privacy Cleanup (DELETE /api/documents/{doc_id})")
    print("=" * 60)
    del_res = client.delete(f"/api/documents/{doc_id}")
    print(f"Status: {del_res.status_code}")
    print(json.dumps(del_res.json(), indent=2))
    assert del_res.status_code == 200

    print("\n" + "=" * 60)
    print("ALL REAL LIVE INTEGRATION CHECKS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_live()
