"""Document analysis service — orchestrates the analysis pipeline.

Pipeline:
1. Extract text from PDF (document_processor)
2. Generate structured analysis via Gemini
3. Validate/verify output (verifier)
4. Return typed result
"""

import logging

from app.core.logging import Timer
from app.models.schemas import (
    DocumentAnalysis,
    DocumentAnswer,
    DocumentComparison,
    ProfessionalPrep,
    SupportStatus,
)
from app.prompts.analysis import ANALYSIS_SYSTEM_PROMPT, LANGUAGE_MAP, build_analysis_prompt
from app.prompts.comparison import COMPARISON_SYSTEM_PROMPT, build_comparison_prompt
from app.prompts.qa import QA_SYSTEM_PROMPT, build_qa_prompt
from app.services.document_processor import ProcessedDocument
from app.services.gemini import generate_structured_response
from app.services.verifier import verify_analysis, verify_answer, verify_comparison

logger = logging.getLogger("legallens.analyzer")


async def analyze_document(
    doc: ProcessedDocument,
    concerns: list[str],
    custom_concern: str = "",
    language: str = "en",
) -> DocumentAnalysis:
    """Run the full analysis pipeline on a processed document.

    Steps:
    1. Build evidence-first prompt with user concerns
    2. Send document text + prompt to Gemini
    3. Parse structured JSON response into DocumentAnalysis
    4. Run deterministic verification
    5. Return validated analysis
    """
    lang_instruction = LANGUAGE_MAP.get(language, LANGUAGE_MAP["en"])
    system_prompt = ANALYSIS_SYSTEM_PROMPT.format(language_instruction=lang_instruction)
    user_prompt = build_analysis_prompt(concerns, custom_concern, language)

    with Timer("Document analysis", logger):
        raw_result = await generate_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document_text=doc.full_text,
            response_schema=DocumentAnalysis,
        )

    # Parse into structured model
    try:
        analysis = DocumentAnalysis.model_validate(raw_result)
    except Exception as exc:
        logger.error("Failed to validate analysis response: %s", exc)
        # Return a minimal safe analysis
        analysis = DocumentAnalysis(
            document_type="Unknown",
            summary="Analysis could not be fully structured. Please try again.",
            missing_information=[],
        )

    # Run deterministic verification
    analysis = verify_analysis(analysis, known_doc_names={doc.filename})

    logger.info(
        "Analysis complete: %d findings, %d obligations, %d missing items",
        len(analysis.findings),
        len(analysis.obligations),
        len(analysis.missing_information),
    )
    return analysis


async def ask_document(
    doc: ProcessedDocument,
    question: str,
    language: str = "en",
) -> DocumentAnswer:
    """Answer a question about a document using evidence-first approach."""
    lang_instruction = LANGUAGE_MAP.get(language, LANGUAGE_MAP["en"])
    system_prompt = QA_SYSTEM_PROMPT.format(language_instruction=lang_instruction)
    user_prompt = build_qa_prompt(question, language)

    with Timer("Document Q&A", logger):
        raw_result = await generate_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document_text=doc.full_text,
            response_schema=DocumentAnswer,
        )

    try:
        answer = DocumentAnswer.model_validate(raw_result)
    except Exception as exc:
        logger.error("Failed to validate Q&A response: %s", exc)
        answer = DocumentAnswer(
            answer="Unable to process your question. Please try rephrasing.",
            support_status=SupportStatus.AMBIGUOUS,
        )

    answer = verify_answer(answer, known_doc_names={doc.filename})
    return answer


async def compare_documents(
    doc_a: ProcessedDocument,
    doc_b: ProcessedDocument,
    concerns: list[str],
    custom_concern: str = "",
    language: str = "en",
) -> DocumentComparison:
    """Compare two documents with structured change detection."""
    lang_instruction = LANGUAGE_MAP.get(language, LANGUAGE_MAP["en"])
    system_prompt = COMPARISON_SYSTEM_PROMPT.format(language_instruction=lang_instruction)
    user_prompt = build_comparison_prompt(concerns, custom_concern, language)

    # Combine both documents clearly labeled
    combined_text = (
        f"=== DOCUMENT A: {doc_a.filename} ===\n{doc_a.full_text}\n\n"
        f"=== DOCUMENT B: {doc_b.filename} ===\n{doc_b.full_text}"
    )

    with Timer("Document comparison", logger):
        raw_result = await generate_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document_text=combined_text,
            response_schema=DocumentComparison,
        )

    try:
        comparison = DocumentComparison.model_validate(raw_result)
    except Exception as exc:
        logger.error("Failed to validate comparison response: %s", exc)
        comparison = DocumentComparison(
            summary="Comparison could not be fully structured. Please try again.",
        )

    comparison = verify_comparison(comparison, doc_a.filename, doc_b.filename)
    return comparison


async def prepare_for_professional(
    analysis: DocumentAnalysis,
    language: str = "en",
) -> ProfessionalPrep:
    """Generate a meeting preparation sheet from an existing analysis.

    This is derived from the analysis without an additional API call.
    """
    prep = ProfessionalPrep(
        what_i_understand=[],
        what_is_unclear=[],
        potential_inconsistencies=[],
        missing_from_document=[],
        questions_to_ask=[],
        important_sections=[],
    )

    # What I understand — from supported findings
    for finding in analysis.findings:
        if finding.support_status == SupportStatus.SUPPORTED:
            prep.what_i_understand.append(f"{finding.title}: {finding.plain_language}")

    # Key facts
    for fact in analysis.key_facts:
        prep.what_i_understand.append(f"{fact.label}: {fact.value}")

    # What is unclear — from ambiguous/partially supported findings
    for finding in analysis.findings:
        if finding.support_status in (SupportStatus.AMBIGUOUS, SupportStatus.PARTIALLY_SUPPORTED):
            prep.what_is_unclear.append(f"{finding.title}: {finding.plain_language}")

    # Missing from document
    for missing in analysis.missing_information:
        prep.missing_from_document.append(missing.topic)
        prep.questions_to_ask.append(missing.suggested_question)

    # Important sections from evidence
    sections_seen: set[str] = set()
    for finding in analysis.findings:
        for evidence in finding.evidence:
            section_ref = ""
            if evidence.section:
                section_ref = f"Section {evidence.section}"
            if evidence.page_number:
                section_ref += f" (Page {evidence.page_number})"
            section_ref = section_ref.strip()
            if section_ref and section_ref not in sections_seen:
                sections_seen.add(section_ref)
                prep.important_sections.append(section_ref)

    return prep
