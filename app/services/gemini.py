"""Gemini API service — centralized Google GenAI SDK integration.

Provides GeminiService for structured generation, File Search grounded responses,
Google Search grounding, and health diagnostics with secure error translation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from google import genai
from google.genai import errors, types

from app.config import get_settings
from app.core.errors import GeminiAPIError, GeminiNotConfiguredError

logger = logging.getLogger("legallens.gemini")


def _sanitize_error_for_user(exc: Exception) -> str:
    """Return a safe, user-friendly error message without leaking sensitive details."""
    if isinstance(exc, errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", 400)
        message = str(exc)
        if "leaked" in message.lower():
            return "Google AI API key was reported as compromised. Please update GEMINI_API_KEY in your configuration."
        if code == 403:
            return "Google AI service access denied. Please verify your API key and permissions."
        if code == 429:
            return "Google AI quota is temporarily unavailable. Please retry in a few moments."
        if code == 404:
            return "The requested Gemini model or resource is not available."
        return "Invalid request to Google AI service."
    elif isinstance(exc, errors.ServerError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", 500)
        if code == 503:
            return "Google AI service is currently experiencing high demand. Please try again shortly."
        return "Google AI service encountered a temporary error. Please try again."
    return "AI service request failed. Please try again."


class GeminiService:
    """Centralized service managing all interactions with Google Gemini API."""

    _instance: GeminiService | None = None

    def __init__(self) -> None:
        self._client: genai.Client | None = None
        self._last_key: str = ""

    @classmethod
    def get_instance(cls) -> GeminiService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_client(self) -> genai.Client:
        """Get or initialize the Google GenAI client."""
        settings = get_settings()
        if not settings.gemini_configured:
            raise GeminiNotConfiguredError()

        if self._client is None or self._last_key != settings.gemini_api_key:
            self._client = genai.Client(api_key=settings.gemini_api_key)
            self._last_key = settings.gemini_api_key
            logger.info("Gemini client initialized with model=%s", settings.gemini_model)

        return self._client

    async def health_check(self) -> dict[str, Any]:
        """Verify Gemini connectivity without leaking API secrets."""
        settings = get_settings()
        if not settings.gemini_configured:
            return {
                "configured": False,
                "reachable": False,
                "model": settings.gemini_model,
                "message": "GEMINI_API_KEY not configured",
            }

        start_time = time.perf_counter()
        client = self.get_client()
        models_to_try = [settings.gemini_model]
        for candidate in ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"):
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        resp = None
        used_model = settings.gemini_model
        last_exc = None
        for m in models_to_try:
            try:
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda model=m: client.models.generate_content(
                        model=model,
                        contents="Reply exactly LEGALLENS_OK",
                        config=types.GenerateContentConfig(
                            max_output_tokens=50,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                        ),
                    ),
                )
                if resp and resp.text:
                    used_model = m
                    logger.info("Gemini health check succeeded using model=%s", m)
                    break
            except Exception as exc:
                last_exc = exc
                logger.warning("Gemini health check on %s failed: %s; trying fallback...", m, type(exc).__name__)

        latency_ms = round((time.perf_counter() - start_time) * 1000, 1)
        if resp and resp.text:
            return {
                "configured": True,
                "reachable": True,
                "model": used_model,
                "latency_ms": latency_ms,
            }
        else:
            return {
                "configured": True,
                "reachable": False,
                "model": settings.gemini_model,
                "latency_ms": latency_ms,
                "error": type(last_exc).__name__ if last_exc else "EmptyResponse",
            }

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        document_text: str | None = None,
        response_schema: Any | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Generate a structured JSON response with retries and fallback for transient 503/429 errors."""
        settings = get_settings()
        client = self.get_client()

        contents: list[str] = []
        if document_text:
            contents.append(f"<DOCUMENT_DATA>\n{document_text}\n</DOCUMENT_DATA>")
        contents.append(user_prompt)

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": 0.1,
            "top_p": 0.95,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        }
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema

        config = types.GenerateContentConfig(**config_kwargs)

        models_to_try = [settings.gemini_model]
        for candidate in ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"):
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        last_exc: Exception | None = None
        for current_model in models_to_try:
            for attempt in range(max_retries + 1):
                try:
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda m=current_model: client.models.generate_content(
                            model=m,
                            contents=contents,
                            config=config,
                        ),
                    )

                    if not response or not response.text:
                        raise GeminiAPIError("Empty response from Google AI service.")

                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                    logger.info("Structured response generated successfully using model=%s", current_model)
                    return json.loads(text)

                except GeminiNotConfiguredError:
                    raise
                except json.JSONDecodeError as exc:
                    logger.error("Failed to parse Gemini JSON output: %s", exc)
                    raise GeminiAPIError("AI service returned an invalid JSON response.") from exc
                except (errors.ServerError, errors.ClientError) as exc:
                    last_exc = exc
                    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                    logger.warning(
                        "Gemini API attempt %d failed (status=%s, type=%s, model=%s)",
                        attempt + 1,
                        status_code,
                        type(exc).__name__,
                        current_model,
                    )
                    # If quota exhausted (429) or persistent 503 on primary model, try next fallback model immediately
                    if status_code in (429, 503) and current_model != models_to_try[-1]:
                        logger.info("Switching to fallback model due to status %s on %s", status_code, current_model)
                        break
                    # If unauthorized or leaked key, do not silently try fallbacks
                    if status_code in (401, 403):
                        break
                    if attempt < max_retries and status_code in (503, 429, 500):
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    break
                except Exception as exc:
                    last_exc = exc
                    logger.error("Unexpected error in Gemini generation: %s", type(exc).__name__)
                    break

        safe_msg = _sanitize_error_for_user(last_exc) if last_exc else "AI service request failed."
        raise GeminiAPIError(safe_msg) from last_exc

    async def generate_search_grounded_response(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Generate response with Google Search grounding for external legal research."""
        settings = get_settings()
        client = self.get_client()

        models_to_try = [settings.gemini_model]
        for candidate in ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"):
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        loop = asyncio.get_running_loop()
        response = None
        last_exc: Exception | None = None

        for current_model in models_to_try:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda m=current_model: client.models.generate_content(
                        model=m,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.2,
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                        ),
                    ),
                )
                if response and response.text:
                    logger.info("Search-grounded response generated successfully using model=%s", current_model)
                    break
            except GeminiNotConfiguredError:
                raise
            except (errors.ServerError, errors.ClientError) as exc:
                last_exc = exc
                status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                logger.warning(
                    "Google Search Grounding attempt on %s failed (status=%s): %s",
                    current_model,
                    status_code,
                    type(exc).__name__,
                )
                if status_code in (401, 403):
                    break
                if status_code in (429, 503):
                    continue
                break
            except Exception as exc:
                last_exc = exc
                logger.warning("Google Search Grounding attempt on %s failed: %s", current_model, type(exc).__name__)
                break

        if not response or not response.text:
            safe_msg = _sanitize_error_for_user(last_exc) if last_exc else "Google Search Grounding query failed."
            raise GeminiAPIError(safe_msg) from last_exc

        citations: list[dict[str, Any]] = []
        context_text = response.text or ""

        # Extract citations from Google Search grounding metadata
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    if hasattr(chunk, "web") and chunk.web:
                        citations.append({
                            "title": getattr(chunk.web, "title", "Web Source"),
                            "url": getattr(chunk.web, "uri", ""),
                            "source": "Google Search Grounding",
                        })

        return {
            "context": context_text,
            "citations": citations,
        }


# ── Backward-compatible helper functions ──────────────────────────────────────────


def get_gemini_client() -> genai.Client:
    """Return the underlying GenAI client."""
    return GeminiService.get_instance().get_client()


async def generate_structured_response(
    system_prompt: str,
    user_prompt: str,
    document_text: str | None = None,
    response_schema: Any | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper around GeminiService.generate_structured with <DOCUMENT_DATA> tags."""
    return await GeminiService.get_instance().generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        document_text=document_text,
        response_schema=response_schema,
    )


async def generate_with_search_grounding(
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Compatibility wrapper around GeminiService.generate_search_grounded_response."""
    return await GeminiService.get_instance().generate_search_grounded_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def get_gemini_service() -> GeminiService:
    """Return singleton GeminiService instance."""
    return GeminiService.get_instance()
