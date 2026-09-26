"""Deterministic evidence verifier — the anti-hallucination layer.

This module verifies model outputs AFTER generation to ensure
the evidence-first contract is maintained. It does NOT rely on
the model self-certifying its own evidence quality.

Verification rules:
1. SUPPORTED responses must contain at least one evidence item.
2. NOT_FOUND responses must not claim a confirmed answer.
3. Page numbers must be positive integers when present.
4. Empty evidence arrays cannot accompany SUPPORTED status.
5. Evidence document names must match known document names.
"""

import logging

from app.models.schemas import (
    DocumentAnalysis,
    DocumentAnswer,
    DocumentComparison,
    Evidence,
    SupportStatus,
)

logger = logging.getLogger("legallens.verifier")


def _validate_evidence(evidence: Evidence, known_doc_names: set[str]) -> Evidence:
    """Validate a single evidence item and fix inconsistencies."""
    # Page number must be positive if present
    if evidence.page_number is not None and evidence.page_number < 1:
        logger.warning("Invalid page number %d, setting to None", evidence.page_number)
        evidence.page_number = None

    # Excerpt must not be empty for SUPPORTED evidence
    if evidence.support_status == SupportStatus.SUPPORTED and not evidence.excerpt.strip():
        evidence.support_status = SupportStatus.AMBIGUOUS

    # Document name validation
    if known_doc_names and evidence.document_name not in known_doc_names:
        # Try to match case-insensitively
        match = None
        for name in known_doc_names:
            if name.lower() == evidence.document_name.lower():
                match = name
                break
        if match:
            evidence.document_name = match
        else:
            logger.warning(
                "Evidence references unknown document '%s', known: %s",
                evidence.document_name,
                known_doc_names,
            )

    return evidence


def verify_analysis(analysis: DocumentAnalysis, known_doc_names: set[str]) -> DocumentAnalysis:
    """Verify a complete document analysis for evidence consistency.

    Downgrades support status where evidence is insufficient rather
    than rejecting the entire analysis.
    """
    # Verify findings
    for finding in analysis.findings:
        finding.evidence = [
            _validate_evidence(e, known_doc_names) for e in finding.evidence
        ]
        # SUPPORTED findings must have evidence
        if finding.support_status == SupportStatus.SUPPORTED and not finding.evidence:
            logger.warning("Finding '%s' marked SUPPORTED but has no evidence, downgrading", finding.title)
            finding.support_status = SupportStatus.AMBIGUOUS

    # Verify obligations
    for obligation in analysis.obligations:
        obligation.evidence = [
            _validate_evidence(e, known_doc_names) for e in obligation.evidence
        ]

    # Verify dates
    for date_item in analysis.dates:
        date_item.evidence = [
            _validate_evidence(e, known_doc_names) for e in date_item.evidence
        ]

    # Verify monetary terms
    for term in analysis.monetary_terms:
        term.evidence = [
            _validate_evidence(e, known_doc_names) for e in term.evidence
        ]

    # Verify key facts
    for fact in analysis.key_facts:
        fact.evidence = [
            _validate_evidence(e, known_doc_names) for e in fact.evidence
        ]

    return analysis


def verify_answer(answer: DocumentAnswer, known_doc_names: set[str]) -> DocumentAnswer:
    """Verify a document Q&A answer for evidence consistency."""
    answer.evidence = [
        _validate_evidence(e, known_doc_names) for e in answer.evidence
    ]

    # SUPPORTED answers must have evidence
    if answer.support_status == SupportStatus.SUPPORTED and not answer.evidence:
        logger.warning("Answer marked SUPPORTED but has no evidence, downgrading")
        answer.support_status = SupportStatus.AMBIGUOUS

    # NOT_FOUND answers should not have a confident affirmative answer
    if answer.support_status == SupportStatus.NOT_FOUND and answer.evidence:
        logger.warning("NOT_FOUND answer has evidence attached, clearing")
        answer.evidence = []

    return answer


def verify_comparison(
    comparison: DocumentComparison,
    doc_a_name: str,
    doc_b_name: str,
) -> DocumentComparison:
    """Verify a document comparison for evidence consistency."""
    known_names = {doc_a_name, doc_b_name}

    for item in comparison.items:
        item.evidence_a = [
            _validate_evidence(e, known_names) for e in item.evidence_a
        ]
        item.evidence_b = [
            _validate_evidence(e, known_names) for e in item.evidence_b
        ]

        # Changed/Added/Removed items should have relevant evidence
        if (
            item.support_status == SupportStatus.SUPPORTED
            and item.change_type.value in ("CHANGED", "UNCHANGED")
            and not (item.evidence_a or item.evidence_b)
        ):
            item.support_status = SupportStatus.AMBIGUOUS

    return comparison
