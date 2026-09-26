"""Local benchmark for LegalLens core operations (no real API calls).

Measures wall-clock time and memory for deterministic operations:
- PDF validation
- PDF text extraction (PyMuPDF)
- SHA-256 hashing
- Evidence verification
- Schema validation & serialization

Usage:
    python scripts/benchmark_local.py
"""

import sys
import time
import tracemalloc

# Ensure project root on path
sys.path.insert(0, ".")


def make_pdf_bytes(text: str = "Sample legal document content for testing.") -> bytes:
    """Create minimal valid PDF bytes."""
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


def benchmark(label: str, func, *args, iterations: int = 100):
    """Run func N times and report stats."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func(*args)
        elapsed_ms = (time.perf_counter() - start) * 1000
        times.append(elapsed_ms)

    avg = sum(times) / len(times)
    p50 = sorted(times)[len(times) // 2]
    p99 = sorted(times)[int(len(times) * 0.99)]
    print(f"  {label:40s}  avg={avg:7.2f}ms  p50={p50:7.2f}ms  p99={p99:7.2f}ms  (n={iterations})")


def main():
    print("=" * 80)
    print("LegalLens Local Benchmark (no API calls)")
    print("=" * 80)

    pdf_bytes = make_pdf_bytes("This is a representative employment agreement clause.")

    # 1. PDF Magic Validation
    from app.core.security import validate_pdf_magic

    benchmark("PDF magic validation", validate_pdf_magic, pdf_bytes)

    # 2. Filename Sanitization
    from app.core.security import sanitize_filename

    benchmark("Filename sanitization", sanitize_filename, "../../etc/evil_<file>.pdf")

    # 3. SHA-256 Hashing
    from app.core.security import compute_file_hash

    benchmark("SHA-256 file hash", compute_file_hash, pdf_bytes)

    # 4. PDF Text Extraction (PyMuPDF)
    from app.services.document_processor import extract_text_from_pdf

    benchmark("PDF text extraction", extract_text_from_pdf, pdf_bytes, "test.pdf", iterations=50)

    # 5. Schema Validation
    from app.models.schemas import DocumentAnalysis

    analysis_data = {
        "document_type": "Employment Agreement",
        "summary": "Test summary",
        "key_facts": [{"label": "Parties", "value": "Employer and Employee"}],
        "findings": [
            {
                "category": "compensation",
                "title": "Base Salary",
                "plain_language": "Salary is $120,000",
                "why_it_matters": "Financial term",
                "evidence": [
                    {
                        "document_name": "test.pdf",
                        "page_number": 1,
                        "excerpt": "annual salary of $120,000",
                        "support_status": "SUPPORTED",
                    }
                ],
                "support_status": "SUPPORTED",
            }
        ],
        "obligations": [],
        "dates": [],
        "monetary_terms": [],
        "missing_information": [],
    }
    benchmark(
        "DocumentAnalysis validation",
        DocumentAnalysis.model_validate,
        analysis_data,
        iterations=200,
    )

    # 6. Evidence Verifier
    from app.services.verifier import verify_analysis

    analysis = DocumentAnalysis.model_validate(analysis_data)
    benchmark("Evidence verification", verify_analysis, analysis, {"test.pdf"}, iterations=500)

    # 7. Serialization round-trip
    benchmark("Analysis model_dump", analysis.model_dump, iterations=500)

    # 8. Memory measurement
    print("\n--- Peak Memory ---")
    tracemalloc.start()
    large_text = "Legal clause. " * 5000
    large_pdf = make_pdf_bytes(large_text[:2000])
    _ = extract_text_from_pdf(large_pdf, "large_test.pdf")
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  PDF extraction peak memory: {peak / 1024:.1f} KB")

    print("\n" + "=" * 80)
    print("Benchmark complete")
    print("=" * 80)


if __name__ == "__main__":
    main()
