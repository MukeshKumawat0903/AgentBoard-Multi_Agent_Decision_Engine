"""
GROQ LLM client wrapper.

Reusable async client for structured LLM calls via the GROQ API.
Supports plain-text and structured JSON responses, exponential-backoff
retries, and per-call timing logs.
"""

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError

logger = logging.getLogger("agentboard.services.llm_client")

_MAX_RETRIES = 2
_BACKOFF_SECONDS: list[float] = [1.0, 2.0]


class GroqClient:
    """
    Reusable async GROQ API client for structured LLM calls.

    Usage:
        client = GroqClient(api_key=..., model=..., base_url=...)
        text   = await client.chat(system_prompt, user_prompt)
        data   = await client.chat_json(system_prompt, user_prompt)
    """

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        """
        Initialise the GROQ client.

        Args:
            api_key:  GROQ API key (Bearer token).
            model:    Model identifier, e.g. "llama-3.3-70b-versatile".
            base_url: Base URL of the GROQ OpenAI-compatible API.
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def close(self) -> None:
        """Close the underlying httpx client – call on app shutdown."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Send a chat-completion request and return the raw text response.

        Args:
            system_prompt: The system / role instruction for the LLM.
            user_prompt:   The user message / task description.
            temperature:   Sampling temperature (0.0 = deterministic).
            max_tokens:    Maximum tokens in the response.

        Returns:
            Raw response string from the LLM.

        Raises:
            LLMConnectionError: Network or API connectivity failure.
            LLMRateLimitError:  API returned HTTP 429.
            LLMResponseError:   Unexpected response structure.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return await self._post_with_retry(payload)

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        Send a chat request that **enforces** structured JSON output.

        Appends a JSON-only enforcement clause to the system prompt and
        sets ``response_format`` to ``json_object``.  Retries once on
        JSON-parse failure with an explicit correction message.

        Args:
            system_prompt: The system / role instruction.
            user_prompt:   The user message / task description.
            temperature:   Lower temperature → more deterministic JSON.

        Returns:
            Parsed Python dict from the LLM response.

        Raises:
            LLMConnectionError: Network or API connectivity failure.
            LLMRateLimitError:  API returned HTTP 429.
            LLMResponseError:   JSON cannot be parsed after retries.
        """
        json_system_prompt = (
            system_prompt
            + "\n\nIMPORTANT: You MUST respond with valid JSON only. "
            "No markdown, no code fences, no extra text. Only raw JSON."
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": json_system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }

        raw = await self._post_with_retry(payload)

        # --- First parse attempt ---
        # NOTE: Python 3 deletes `as exc` variables after the except block,
        # so we save it explicitly before the block exits.
        _saved_first_exc: json.JSONDecodeError | None = None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as first_exc:
            _saved_first_exc = first_exc
            logger.warning(
                "JSON parse failed on first attempt – retrying with correction",
                extra={"raw_preview": raw[:300]},
            )

        # --- Retry: append correction turn ---
        payload["messages"].append({"role": "assistant", "content": raw})
        payload["messages"].append({
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Return ONLY a valid JSON object, nothing else."
            ),
        })
        raw_retry = await self._post_with_retry(payload)

        try:
            return json.loads(raw_retry)
        except json.JSONDecodeError:
            logger.error(
                "JSON parse failed after retry",
                extra={"raw_preview": raw_retry[:300]},
            )
            raise LLMResponseError(
                f"LLM returned unparseable JSON after retry. "
                f"Preview: {raw_retry[:300]}"
            ) from _saved_first_exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post_with_retry(self, payload: dict[str, Any]) -> str:
        """
        POST to ``/chat/completions`` with exponential-backoff retries.

        Retries up to ``_MAX_RETRIES`` times on:
        - HTTP 429 (rate limit)
        - HTTP 5xx (server errors)
        - Network / timeout errors

        Returns the raw content string from the first successful response.
        """
        prompt_chars = sum(
            len(m.get("content", "")) for m in payload.get("messages", [])
        )
        last_exc: Exception = LLMConnectionError("Unknown error in _post_with_retry")

        for attempt in range(_MAX_RETRIES + 1):
            start_time = time.monotonic()
            try:
                response = await self._client.post("/chat/completions", json=payload)
                elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)

                logger.info(
                    "GROQ API call completed",
                    extra={
                        "model":        self.model,
                        "status_code":  response.status_code,
                        "elapsed_ms":   elapsed_ms,
                        "prompt_chars": prompt_chars,
                        "attempt":      attempt + 1,
                    },
                )

                # --- Rate limit ---
                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get(
                            "retry-after",
                            _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)],
                        )
                    )
                    logger.warning(
                        "Rate limited by GROQ API",
                        extra={"retry_after_s": retry_after, "attempt": attempt + 1},
                    )
                    last_exc = LLMRateLimitError("GROQ API rate limit exceeded (429)")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(retry_after)
                        continue
                    raise last_exc

                # --- Server errors ---
                if response.status_code >= 500:
                    logger.warning(
                        "GROQ API server error",
                        extra={"status_code": response.status_code, "attempt": attempt + 1},
                    )
                    last_exc = LLMConnectionError(
                        f"GROQ API server error: {response.status_code}"
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(
                            _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                        )
                        continue
                    raise last_exc

                response.raise_for_status()

                # --- Parse response ---
                data = response.json()
                content: str = data["choices"][0]["message"]["content"]
                return content

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
                logger.warning(
                    "GROQ API network error",
                    extra={
                        "error":      str(exc),
                        "elapsed_ms": elapsed_ms,
                        "attempt":    attempt + 1,
                    },
                )
                last_exc = LLMConnectionError(
                    f"Network error connecting to GROQ: {exc}"
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(
                        _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                    )
                    continue
                raise LLMConnectionError(
                    f"Network error after {attempt + 1} attempt(s): {exc}"
                ) from exc

            except (KeyError, IndexError) as exc:
                raise LLMResponseError(
                    f"Unexpected GROQ response structure: {exc}"
                ) from exc

        raise last_exc


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_llm_client_instance: GroqClient | None = None


def get_llm_client() -> GroqClient:
    """
    Return the singleton GroqClient loaded from application settings.

    Creates the instance lazily on the first call.  Import and call this
    anywhere inside the application to share one httpx connection pool.
    """
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = GroqClient(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            base_url=settings.GROQ_BASE_URL,
        )
        logger.info(
            "GroqClient singleton initialised",
            extra={"model": settings.GROQ_MODEL, "base_url": settings.GROQ_BASE_URL},
        )
    return _llm_client_instance
