"""Pydantic schemas for structured LegalLens data models.

These schemas enforce the evidence-first architecture: every factual claim
about a document must carry evidence and a support status.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────────────


class SupportStatus(str, Enum):
    """How well a claim is supported by document evidence."""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"


class ChangeType(str, Enum):
    """Type of change detected in document comparison."""
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class ConcernCategory(str, Enum):
    """Pre-defined concern categories for personalized review."""
    SALARY_COMPENSATION = "salary_compensation"
    NOTICE_PERIOD = "notice_period"
    TERMINATION = "termination"
    PROBATION = "probation"
    NON_COMPETE = "non_compete"
    CONFIDENTIALITY = "confidentiality"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    WORKING_HOURS = "working_hours"
    LOCATION = "location"
    LEAVE = "leave"
    BOND_REPAYMENT = "bond_repayment"
    STOCK_OPTIONS = "stock_options"
    MONEY_PAYMENT = "money_payment"
    DEADLINES = "deadlines"
    OBLIGATIONS = "obligations"
    CANCELLATION = "cancellation"
    PENALTIES = "penalties"
    RENEWAL = "renewal"
    PRIVACY = "privacy"
    LIABILITY = "liability"
    DISPUTE_RESOLUTION = "dispute_resolution"
    UNUSUAL_RESTRICTIONS = "unusual_restrictions"
    OTHER = "other"


# ── Evidence ───────────────────────────────────────────────────────────────────


class Evidence(BaseModel):
    """A piece of evidence from a source document backing a claim."""
    document_name: str = Field(description="Name of the source document")
    page_number: int | None = Field(default=None, description="Page number (1-indexed) or None if unavailable")
    section: str | None = Field(default=None, description="Clause or section identifier if detectable")
    excerpt: str = Field(description="Short supporting excerpt from the document")
    support_status: SupportStatus = Field(description="How well this evidence supports the claim")


# ── Findings & Obligations ─────────────────────────────────────────────────────


class Finding(BaseModel):
    """A structured finding from document analysis."""
    category: str = Field(description="Concern category this finding relates to")
    title: str = Field(description="Concise heading for the finding")
    plain_language: str = Field(description="Plain-language explanation of the finding")
    why_it_matters: str = Field(description="Why this may matter to the user's concern")
    evidence: list[Evidence] = Field(default_factory=list)
    support_status: SupportStatus = SupportStatus.NOT_FOUND


class Obligation(BaseModel):
    """A contractual obligation extracted from the document."""
    actor: str = Field(description="Who must perform the obligation")
    action: str = Field(description="What must be done")
    deadline: str | None = Field(default=None, description="When it must be done")
    consequence: str | None = Field(default=None, description="Consequence stated in document")
    evidence: list[Evidence] = Field(default_factory=list)


class DateItem(BaseModel):
    """An important date or deadline extracted from the document."""
    description: str = Field(description="What the date relates to")
    date_text: str = Field(description="The date as stated in the document")
    evidence: list[Evidence] = Field(default_factory=list)


class MonetaryTerm(BaseModel):
    """A monetary term extracted from the document."""
    description: str = Field(description="Type: salary, fee, penalty, deposit, etc.")
    amount: str = Field(description="The amount as stated in the document")
    details: str | None = Field(default=None, description="Additional details or conditions")
    evidence: list[Evidence] = Field(default_factory=list)


class KeyFact(BaseModel):
    """A key structured fact about the document."""
    label: str = Field(description="Fact label: parties, effective date, duration, etc.")
    value: str = Field(description="The fact value")
    evidence: list[Evidence] = Field(default_factory=list)


# ── Missing Information ────────────────────────────────────────────────────────


class MissingInformation(BaseModel):
    """Information that the user may want but is absent from the document."""
    topic: str = Field(description="What information is missing")
    explanation: str = Field(description="Why the user may want this clarified")
    suggested_question: str = Field(description="Question the user could ask the counterparty or lawyer")


# ── Document Analysis ──────────────────────────────────────────────────────────


class DocumentAnalysis(BaseModel):
    """Complete structured analysis of a legal document."""
    document_type: str = Field(description="Detected document type: employment agreement, lease, NDA, etc.")
    summary: str = Field(description="Brief plain-language summary of the document")
    key_facts: list[KeyFact] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    dates: list[DateItem] = Field(default_factory=list)
    monetary_terms: list[MonetaryTerm] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    disclaimer: str = Field(
        default="This analysis provides document information and general assistance, "
        "not professional legal advice. For decisions with legal consequences, "
        "consider consulting a qualified legal professional."
    )


# ── Q&A ────────────────────────────────────────────────────────────────────────


class DocumentAnswer(BaseModel):
    """Structured answer to a user question about the document."""
    answer: str = Field(description="The answer in plain language")
    support_status: SupportStatus = Field(description="How well the answer is supported")
    evidence: list[Evidence] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list, description="Follow-up questions the user may consider")


# ── Comparison ─────────────────────────────────────────────────────────────────


class ComparisonItem(BaseModel):
    """A single difference or similarity detected between two documents."""
    category: str = Field(description="Category: compensation, termination, notice, etc.")
    change_type: ChangeType = Field(description="Type of change")
    document_a_text: str = Field(description="What Document A states")
    document_b_text: str = Field(description="What Document B states")
    explanation: str = Field(description="Plain-language explanation of the difference")
    why_it_matters: str = Field(description="Why this difference may matter")
    evidence_a: list[Evidence] = Field(default_factory=list)
    evidence_b: list[Evidence] = Field(default_factory=list)
    support_status: SupportStatus = SupportStatus.SUPPORTED


class DocumentComparison(BaseModel):
    """Complete comparison between two legal documents."""
    summary: str = Field(description="Overall summary of key differences")
    items: list[ComparisonItem] = Field(default_factory=list)
    missing_in_a: list[str] = Field(default_factory=list, description="Topics present in B but absent from A")
    missing_in_b: list[str] = Field(default_factory=list, description="Topics present in A but absent from B")
    disclaimer: str = Field(
        default="This comparison provides document information and general assistance, "
        "not professional legal advice."
    )


# ── Legal Context Research ─────────────────────────────────────────────────────


class WebCitation(BaseModel):
    """A citation from web search grounding."""
    title: str
    url: str
    snippet: str = ""


class LegalContextResult(BaseModel):
    """Result of external legal context research via Google Search grounding."""
    query: str = Field(description="The user's research query")
    context: str = Field(description="General legal context information")
    citations: list[WebCitation] = Field(default_factory=list)
    disclaimer: str = Field(
        default="General informational context from web sources — not professional legal advice. "
        "This information does NOT come from your uploaded document."
    )


# ── Prepare for Professional ───────────────────────────────────────────────────


class ProfessionalPrep(BaseModel):
    """Meeting preparation sheet for consulting a legal professional."""
    what_i_understand: list[str] = Field(default_factory=list)
    what_is_unclear: list[str] = Field(default_factory=list)
    potential_inconsistencies: list[str] = Field(default_factory=list)
    missing_from_document: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    important_sections: list[str] = Field(default_factory=list)


# ── API Request / Response ─────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """Request body for document analysis (concerns sent alongside file upload)."""
    concerns: list[str] = Field(default_factory=list, description="User's selected concern categories")
    custom_concern: str = Field(default="", description="Free-text concern from user")
    language: str = Field(default="en", description="Explanation language: en, ta, hi")


class AskRequest(BaseModel):
    """Request body for asking a question about an uploaded document."""
    question: str = Field(min_length=1, max_length=1000, description="The user's question")
    document_id: str = Field(description="SHA-256 hash identifier for the uploaded document")
    language: str = Field(default="en")


class CompareRequest(BaseModel):
    """Metadata for a document comparison request."""
    concerns: list[str] = Field(default_factory=list)
    custom_concern: str = Field(default="")
    language: str = Field(default="en")


class ResearchRequest(BaseModel):
    """Request for external legal context research."""
    query: str = Field(min_length=1, max_length=500, description="Legal topic to research")
    jurisdiction: str = Field(default="", description="Optional jurisdiction context")


class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: str
    detail: str | None = None
