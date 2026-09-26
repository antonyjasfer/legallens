"""Gemini API service — centralized Google GenAI SDK integration.

Handles model configuration, structured output generation, and
Google Search grounding for external legal context research.
"""

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.core.errors import GeminiAPIError, GeminiNotConfiguredError

logger = logging.getLogger("legallens.gemini")

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    """Get or create the Gemini client singleton."""
    global _client
    settings = get_settings()

    if not settings.gemini_configured:
        raise GeminiNotConfiguredError()

    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("Gemini client initialized with model=%s", settings.gemini_model)

    return _client


async def generate_structured_response(
    system_prompt: str,
    user_prompt: str,
    document_text: str | None = None,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a structured JSON response from Gemini.

    Args:
        system_prompt: System instructions for the model.
        user_prompt: User-facing prompt.
        document_text: Optional document text to include as context.
        response_schema: Optional JSON schema for structured output.

    Returns:
        Parsed JSON dictionary from the model response.

    Raises:
        GeminiNotConfiguredError: If API key is not set.
        GeminiAPIError: If the API call fails.
    """
    settings = get_settings()
    client = get_gemini_client()

    contents: list[types.Content | str] = []

    if document_text:
        # Document text is explicitly marked as DATA, not instructions
        contents.append(
            f"<DOCUMENT_DATA>\n{document_text}\n</DOCUMENT_DATA>"
        )

    contents.append(user_prompt)

    generation_config: dict[str, Any] = {
        "temperature": 0.1,  # Low temperature for factual accuracy
        "top_p": 0.95,
        "max_output_tokens": 8192,
    }

    if response_schema:
        generation_config["response_mime_type"] = "application/json"

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=generation_config["temperature"],
                top_p=generation_config["top_p"],
                max_output_tokens=generation_config["max_output_tokens"],
                response_mime_type=generation_config.get("response_mime_type"),
            ),
        )

        if not response.text:
            raise GeminiAPIError("Empty response from AI service.")

        # Parse JSON response
        text = response.text.strip()
        # Handle markdown code fences
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini JSON response: %s", exc)
            logger.debug("Raw response: %s", text[:500])
            raise GeminiAPIError(
                "AI service returned an invalid response format. Please try again."
            ) from exc

        return result

    except GeminiNotConfiguredError:
        raise
    except GeminiAPIError:
        raise
    except Exception as exc:
        logger.error("Gemini API call failed: %s", exc)
        raise GeminiAPIError(f"AI service request failed: {type(exc).__name__}") from exc


async def generate_with_search_grounding(
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Generate a response with Google Search grounding for external legal context.

    Uses Gemini's built-in Google Search tool to provide grounded, cited responses.

    Returns:
        Dictionary with 'context' text and 'citations' list.
    """
    settings = get_settings()
    client = get_gemini_client()

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=4096,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        context_text = response.text or ""
        citations = []

        # Extract grounding metadata if available
        if response.candidates:
            candidate = response.candidates[0]
            grounding_meta = getattr(candidate, "grounding_metadata", None)
            if grounding_meta:
                chunks = getattr(grounding_meta, "grounding_chunks", []) or []
                for chunk in chunks:
                    web = getattr(chunk, "web", None)
                    if web:
                        citations.append({
                            "title": getattr(web, "title", ""),
                            "url": getattr(web, "uri", ""),
                            "snippet": "",
                        })

        return {
            "context": context_text,
            "citations": citations,
        }

    except GeminiNotConfiguredError:
        raise
    except Exception as exc:
        logger.error("Gemini Search grounding call failed: %s", exc)
        raise GeminiAPIError(
            "External legal context research is currently unavailable."
        ) from exc
