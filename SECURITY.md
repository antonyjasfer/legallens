# Security — LegalLens

## Threat Model

Legal documents are sensitive. LegalLens handles untrusted file uploads and processes them through AI services.

### Attack Surface

| Vector | Mitigation |
|--------|-----------|
| Malicious file upload | Size limits, MIME validation, PDF magic byte check |
| Path traversal via filename | Filename sanitization, directory component stripping |
| Prompt injection via document | Document wrapped as DATA, system prompt defense |
| API key exposure | Environment variables, no hardcoded secrets |
| XSS via model output | HTML escaping of all rendered content |
| Excessive requests | Configurable limits, timeouts |

## File Upload Security

1. **Size limit**: Configurable `MAX_UPLOAD_MB` (default: 10 MB)
2. **MIME type check**: Only `application/pdf` accepted
3. **Magic byte validation**: First 4 bytes must be `%PDF`
4. **Filename sanitization**: Strip directory components, replace special characters, truncate length
5. **No execution**: Document content is never executed
6. **Temporary storage**: Files cleaned after processing

## Prompt Injection Defense

All prompts include:
- Document text is explicitly marked as **untrusted DATA**
- System instructions prohibit following commands in document text
- System prompts are not disclosed on request
- Content is wrapped in `<DOCUMENT_DATA>` tags

## HTTP Security Headers

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | Restrictive policy allowing self and Google Fonts |

## Secret Management

- **Development**: `.env` file (gitignored)
- **Production**: Google Cloud Secret Manager
- **Never committed**: API keys, credentials, tokens
- `.env.example` provided with placeholder values

## Error Handling

- Production mode: Generic error messages
- Development mode: Detailed errors for debugging
- No raw stack traces to users
- No document content in logs

## Dependency Security

- Dependencies pinned in `requirements.txt`
- Minimal dependency set
- No unused packages
