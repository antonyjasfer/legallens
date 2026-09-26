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
- **`document_processor.py`** — PDF text extraction with page-level metadata
- **`gemini.py`** — Centralized Gemini API integration
- **`analyzer.py`** — Orchestrates the analysis/QA/comparison pipeline
- **`verifier.py`** — Deterministic post-generation evidence validation
- **`legal_context.py`** — External legal research with Google Search grounding

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
