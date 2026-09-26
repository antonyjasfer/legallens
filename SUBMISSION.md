# Submission — LegalLens

## Describe the changes/updates made in the deployed version

LegalLens is a fully functional evidence-first legal document navigator deployed on Cloud Run. It analyzes uploaded PDF legal documents with personalized concern selection, providing structured findings with page-level evidence citations, obligation extraction, date/monetary term detection, and missing information alerts. Features include evidence-grounded Q&A (returns NOT_FOUND when information is absent), side-by-side document comparison with structured change detection, printable professional consultation preparation sheets, and optional Google Search-grounded external legal context research. Built with FastAPI + Google Gemini API (google-genai SDK), featuring a deterministic anti-hallucination verifier, prompt injection defense, comprehensive accessibility (WCAG), and security headers. All AI responses are validated against Pydantic schemas before display.

## Mention the Gen AI services utilized in the submission, and where did you utilize it?

1. **Google Gemini API** (google-genai Python SDK): Core structured reasoning engine for document analysis, evidence extraction, Q&A, and comparison. Used in `app/services/gemini.py` for all AI generation with structured JSON output, low temperature (0.1) for factual accuracy, and evidence-first prompt constraints.

2. **Gemini Structured Output**: JSON schema enforcement for typed analysis results (DocumentAnalysis, DocumentAnswer, DocumentComparison Pydantic models). Ensures every response follows the evidence-first contract.

3. **Google Search Grounding**: Powers the optional external legal context research feature (`app/services/legal_context.py`). Clearly separated from document-grounded answers with distinct UI labeling. Returns web citations from grounding metadata.

4. **Google Cloud Run**: Containerized deployment via Dockerfile with non-root user, health checks, and PORT environment variable support.

5. **Google Secret Manager**: Recommended for production API key management (documented in README deployment instructions).

### Sample Documents Included
The repository includes ready-to-test realistic legal documents in the `samples/` directory:
- `samples/employment_agreement.pdf` (3-page employment contract with compensation, non-compete, IP assignment, and arbitration clauses)
- `samples/nda_mutual_v1.pdf` (Standard 3-year mutual NDA)
- `samples/nda_strict_v2.pdf` (Revised strict unilateral NDA with liquidated damages and perpetual trade secret confidentiality — ideal for testing document comparison)
- `samples/residential_lease.pdf` (Residential lease with repair fee, rent increase, and pet policy clauses)

### 1. Open App (10s)
Show the LegalLens home page. Point out the 4 trust principles: Evidence Attached, Missing Info Acknowledged, Plain-Language Explanations, Information Not Legal Advice.

### 2. Upload Employment Agreement (20s)
Click "Analyze a Document". Upload `samples/employment_agreement.pdf`. Select concerns: "Notice Period", "Termination", "Salary/Compensation". Add custom concern: "What happens to my work if I leave?"

### 3. Show Personalized Findings (30s)
After analysis loads, show the Overview tab. Scroll through Key Facts (parties, start date, salary). Show findings ranked by selected concerns. Click "View evidence" on a finding — show the page number, section, and source excerpt.

### 4. Show Missing Information (20s)
Switch to the "⚠️ Clarify" tab. Show topics that are ABSENT from the document (e.g., "No vesting schedule mentioned", "Leave encashment policy not specified"). Show suggested questions for each.

### 5. Ask a Question That EXISTS (20s)
Switch to "Ask" tab. Type: "What is my notice period?" Show the SUPPORTED answer with evidence.

### 6. Ask a Question That DOES NOT EXIST (20s)
Type: "What is the stock vesting schedule?" Show the NOT_FOUND response: "This cannot be determined from the document you provided." This is the key differentiator — generic AI would fabricate an answer.

### 7. Compare Two Documents (30s)
Navigate to Compare. Upload two versions of an agreement. Show the structured "What Changed" view with ADDED/REMOVED/CHANGED badges, evidence from both documents.

### 8. Prepare for Professional (15s)
Click "Prepare Questions". Show the printable meeting-prep sheet with "What I Understand", "What is Unclear", "Questions to Ask".

### 9. External Legal Context (15s)
Click "Research Context". Search "notice period laws in India". Show the result clearly labeled "External web information — NOT from your document" with web citations.
