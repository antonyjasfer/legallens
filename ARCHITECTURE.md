# Architecture — LegalLens

## Overview

LegalLens follows a **layered architecture** designed for reliability, testability, and the strict evidence-first contract.

## Layers

### 1. API Layer (`app/api/`)
- FastAPI route handlers
- Request validation via Pydantic models
- File upload handling with security checks
- HTTP error responses

### 2. Service Layer (`app/services/`)
- **`gemini.py`** — Centralized Gemini API client (`gemini-3.8-flash`) with structured schema generation and retries
- **`file_search.py`** — Gemini File Search multimodal document indexing, polling, and citation parsing
- **`gcs.py`** — Google Cloud Storage private uploaded PDF management with local validation and server-controlled naming
- **`firestore.py`** — Cloud Firestore document and session metadata repository (no raw text) with clean local fallback
- **`document_ai.py`** — Google Cloud Document AI Layout Parser for scanned/complex PDF layout extraction
- **`document_processor.py`** — PyMuPDF local text extraction with Document AI fallback
- **`analyzer.py`** — Orchestrates analysis, Q&A, and document comparison pipelines
- **`verifier.py`** — Deterministic post-generation evidence and citation verifier
- **`legal_context.py`** — External legal research using Gemini Google Search grounding (isolated from document RAG)

### 3. Prompt Layer (`app/prompts/`)
- Separated prompt templates for each task (analysis, QA, comparison, research)
- All prompts enforce evidence-first constraints
- Document content explicitly marked as untrusted data

### 4. Model Layer (`app/models/`)
- Pydantic v2 schemas for all data structures
- Enums for support status and change types
- Request/response validation

### 5. Core Layer (`app/core/`)
- Security utilities (file validation, sanitization, headers)
- Structured error hierarchy
- Logging with request ID tracking

## Request Flow

```
Client → FastAPI Middleware (security headers, request ID, timing)
  → Route Handler (validate request, parse file)
    → File Validator (size, MIME, magic bytes, sanitize name)
    → Document Processor (extract text with page numbers)
    → SHA-256 Cache Check
    → Prompt Builder (construct evidence-first prompt)
    → Gemini API (structured JSON generation)
    → Evidence Verifier (deterministic validation)
    → Pydantic Model Validation
  → JSON Response with typed schema
```

## Anti-Hallucination Pipeline

```
Generate → Parse → Validate Schema → Verify Evidence → Respond
                                         │
                                    ┌─────┴──────┐
                                    │ Downgrade   │
                                    │ unsupported │
                                    │ claims      │
                                    └─────────────┘
```

## Caching Strategy

- Documents cached in-memory by SHA-256 hash
- Analysis results cached per document hash
- No sensitive content cached persistently
- Cache is session-scoped (server restart clears it)

## Error Handling

- Structured exception hierarchy (`LegalLensError` base)
- Specific exceptions for each failure mode
- Generic messages in production, detailed in development
- Graceful degradation when Gemini is unavailable

## Technology Stack & Cloud Architecture

LegalLens is deployed live as a FastAPI application on Vercel while its GenAI pipeline uses Google Gemini, Gemini File Search for document-grounded retrieval, and Google Search grounding for isolated external legal context.

### Active Production & GenAI Stack
| Service / Component | Purpose | Architecture Role |
|---|---|---|
| **Vercel Serverless** | Production application hosting | Edge delivery for FastAPI app & static UI (`api/index.py`) |
| **FastAPI (Python 3.12)** | Application backend | High-throughput async REST API & deterministic evidence verifier |
| **Gemini 3.8 Flash** | Document reasoning & structured JSON output | Primary LLM engine using `google-genai` SDK |
| **Gemini File Search** | Multimodal document indexing & evidence citation | Strict document RAG with page and section references |
| **Google Search Grounding** | General external legal context | Isolated research route (`POST /api/legal-context`) |

### Optional Google Cloud Production Integrations
The repository includes clean, tested GCP enterprise connectors with safe local fallbacks:
| Service | Purpose | Status in Current Deployment |
|---|---|---|
| **Google Cloud Storage** | Private encrypted storage for uploaded PDFs | Optional (ephemeral local scratch fallback active) |
| **Cloud Firestore** | Document and session metadata | Optional (in-memory metadata cache fallback active) |
| **Document AI Layout Parser** | Advanced OCR & structural extraction | Optional (PyMuPDF local extraction active) |
| **Secret Manager** | Production credential management for GCP | Optional (Vercel encrypted environment variables active) |
| **Cloud Run** | Containerized serverless hosting | Optional (artifacts retained via `Dockerfile` and `scripts/deploy_cloud_run.ps1`) |
| **Cloud Logging** | Observability & structured telemetry | Optional (local structured logging active) |

## Privacy & Document Lifecycle

Legal contracts are sensitive documents that require strict privacy controls:
1. **Private by Default**: Storage buckets are private; no public URLs are ever generated.
2. **Ephemeral Document Processing**: Files uploaded to Gemini File API and GCS can be cleaned up on demand.
3. **Deterministic Cleanup Endpoint**: `DELETE /api/documents/{document_id}` cascades deletion across GCS, Gemini File Search, Firestore metadata, and local memory caches.
4. **No Raw Text in Firestore**: Only hash, timestamps, and indexing references are persisted.
