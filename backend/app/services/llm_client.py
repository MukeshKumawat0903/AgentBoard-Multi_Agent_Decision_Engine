"""
LangChain-backed multi-provider LLM adapter for AgentBoard.

Replaces the custom GroqClient (httpx) with a provider-agnostic adapter
built on LangChain that supports:

- Multi-provider backends: Groq (default), OpenAI, Anthropic – switchable
  via the LLM_PROVIDER config variable without any code changes.
- Structured output via with_structured_output(): pass a Pydantic model
  class and receive a validated model instance back directly, eliminating
  all manual JSON parsing and retry-on-parse-failure boilerplate.
- Built-in retry: LangChain's with_retry() handles exponential back-off
  on transient failures across every provider automatically.
- LangSmith tracing: when LANGSMITH_TRACING=true in .env, every LLM call
  is automatically traced with token counts, cost, and latency.

GroqClient is kept as a backward-compatible alias so existing imports
in tests and legacy code continue to work without modification.
"""

import logging
from typing import Any, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from pydantic import SecretStr

from app.core.config import settings
from app.utils.exceptions import LLMConnectionError, LLMResponseError

logger = logging.getLogger("agentboard.services.llm_client")

T = TypeVar("T")


class LangChainProvider:
    """
    Multi-provider LLM adapter using LangChain.

    Supports Groq (default), OpenAI, and Anthropic backends, all sharing
    the same async interface.  Provider is selected via the LLM_PROVIDER
    config setting; credentials come from the corresponding *_API_KEY vars.

    Key methods
    -----------
    ainvoke_structured(schema, system_prompt, user_prompt)
        Invoke the LLM and return a validated Pydantic model directly.
        No manual JSON parsing required.  Uses with_structured_output().

    chat(system_prompt, user_prompt, ...)
        Plain text response – for free-form content generation.

    chat_json(system_prompt, user_prompt, ...)
        Backward-compatible dict-returning method for legacy callers.
    """

    def __init__(
        self,
        provider: str = "groq",
        api_key: str = "",
        model: str = "",
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self._llm = self._build_llm(provider, api_key, model)
        logger.info(
            "LangChainProvider initialized",
            extra={"provider": provider, "model": model},
        )

    # ------------------------------------------------------------------
    # Provider factory
    # ------------------------------------------------------------------

    # Models that reject sampling parameters: Anthropic removed temperature/
    # top_p/top_k on Opus 4.7+ and the Fable/Mythos 5 family (400 if sent);
    # OpenAI's gpt-5 reasoning family only supports the default temperature.
    _NO_TEMPERATURE_PREFIXES = (
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable",
        "claude-mythos",
        "gpt-5",
    )

    @classmethod
    def _sampling_kwargs(cls, model: str) -> dict:
        """Return sampling kwargs, omitting temperature where the API rejects it."""
        if model.startswith(cls._NO_TEMPERATURE_PREFIXES):
            return {}
        return {"temperature": 0.7}

    @staticmethod
    def _build_llm(provider: str, api_key: str, model: str):
        """Build the appropriate LangChain chat model for the given provider."""
        secret = SecretStr(api_key) if api_key else None
        sampling = LangChainProvider._sampling_kwargs(model)
        if provider == "groq":
            from langchain_groq import ChatGroq  # type: ignore[import-untyped]
            return ChatGroq(api_key=secret, model=model, **sampling)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
            return ChatOpenAI(api_key=secret, model=model, **sampling)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]
            return ChatAnthropic(api_key=secret, model=model, **sampling)  # type: ignore[call-arg]
        elif provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-untyped]
            return ChatGoogleGenerativeAI(google_api_key=secret, model=model, **sampling)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider!r}")

    @staticmethod
    def get_llm(provider: str, api_key: str, model: str):
        """Build and return a raw LangChain chat model instance.

        Convenience factory used by the AgentRegistry to construct
        per-agent model overrides without creating a full LangChainProvider.
        """
        return LangChainProvider._build_llm(provider, api_key, model)

    @staticmethod
    def _build_messages(system_prompt: str, user_prompt: str):
        """Compose the chat turn using ChatPromptTemplate."""
        template = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                ("human", "{user_prompt}"),
            ]
        )
        return template.format_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ------------------------------------------------------------------
    # Primary structured-output method (Phase 1 core)
    # ------------------------------------------------------------------

    async def ainvoke_structured(
        self,
        schema: type[T],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_retries: int = 2,
    ) -> T:
        """
        Invoke the LLM and return a validated Pydantic model instance.

        Uses LangChain's with_structured_output() for reliable schema
        binding via tool/function calling.  No manual JSON parsing needed.
        Built-in retry on transient failures.

        Args:
            schema:        Pydantic model class the LLM should populate.
            system_prompt: Role/instruction for the model.
            user_prompt:   User turn message.
            temperature:   Sampling temperature (default 0.3 for structured).
            max_retries:   Max LangChain retry attempts (B7: wired from AgentConfig).

        Returns:
            A validated instance of ``schema``.

        Raises:
            LLMResponseError: If structured output fails after retries.
        """
        try:
            llm = cast(Any, self._llm.bind(temperature=temperature))
            # tenacity's stop_after_attempt(0) stops *before* the first attempt,
            # so a config value of 0 ("no retries") must still mean one call.
            chain = llm.with_structured_output(schema).with_retry(
                stop_after_attempt=max(1, max_retries),
                wait_exponential_jitter=True,
            )
            messages = self._build_messages(system_prompt, user_prompt)
            result: T = await chain.ainvoke(messages)
            return result
        except Exception as exc:
            logger.error(
                "ainvoke_structured_failed",
                extra={"schema": schema.__name__, "provider": self.provider, "error": str(exc)},
            )
            raise LLMResponseError(
                f"Structured output failed for {schema.__name__} "
                f"via {self.provider}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Plain text + backward-compat dict methods
    # ------------------------------------------------------------------

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Return a plain-text response from the LLM."""
        try:
            llm = self._llm.bind(temperature=temperature, max_tokens=max_tokens)
            messages = self._build_messages(system_prompt, user_prompt)
            response = await llm.ainvoke(messages)
            if isinstance(response.content, str):
                return response.content
            return str(response.content)
        except Exception as exc:
            raise LLMConnectionError(f"LLM chat call failed: {exc}") from exc

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        Backward-compatible method that returns a raw dict.

        Retained for legacy callers and tests.  New code should prefer
        ainvoke_structured() with an explicit Pydantic schema.
        """
        import json as _json

        raw = await self.chat(system_prompt, user_prompt, temperature=temperature)
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"LLM returned unparseable JSON. Preview: {raw[:300]}"
            ) from exc

    async def close(self) -> None:
        """No-op: LangChain manages HTTP connection pools internally."""
        pass

    def __repr__(self) -> str:
        return f"<LangChainProvider provider={self.provider!r} model={self.model!r}>"


# ---------------------------------------------------------------------------
# Token cost estimation
# ---------------------------------------------------------------------------
# Approximate prices in USD per 1M tokens as (input, output). These are rough
# estimates for surfacing approximate cost only — not billing-accurate. Keys
# track the models offered in PROVIDER_MODELS (app/schemas/api_models.py);
# unknown models fall back to None in estimate_cost_usd.
_MODEL_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    # Groq
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "moonshotai/kimi-k2-instruct-0905": (1.00, 3.00),
    "qwen/qwen3-32b": (0.29, 0.59),
    # OpenAI
    "gpt-5.5": (2.50, 10.00),
    "gpt-5.5-pro": (15.00, 60.00),
    "gpt-5.4-mini": (0.25, 2.00),
    # Anthropic
    "claude-opus-4-8": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-fable-5": (1.00, 5.00),
    # Gemini
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-pro-preview": (1.25, 10.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
}


def estimate_cost_usd(usage_by_model: dict) -> float | None:
    """
    Estimate total cost from per-model usage metadata.

    ``usage_by_model`` maps a model name to a dict with ``input_tokens`` and
    ``output_tokens``.  Returns None if none of the models have a known price.
    """
    total = 0.0
    priced_any = False
    for model, usage in usage_by_model.items():
        price = _MODEL_PRICES_PER_1M.get(model)
        if price is None:
            continue
        in_price, out_price = price
        inp = usage.get("input_tokens", 0) or 0
        out = usage.get("output_tokens", 0) or 0
        total += (inp / 1_000_000) * in_price + (out / 1_000_000) * out_price
        priced_any = True
    return round(total, 6) if priced_any else None


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------
# All existing: `from app.services.llm_client import GroqClient` imports
# resolve to LangChainProvider without any file changes required.
GroqClient = LangChainProvider


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_llm_client_instance: LangChainProvider | None = None
# True when the active client was configured via a user-supplied API key
# (i.e. not the key baked into .env).
_using_custom_key: bool = False


def get_llm_client() -> LangChainProvider:
    """
    Return the singleton LangChainProvider loaded from application settings.

    The active provider is selected via settings.LLM_PROVIDER.
    Creates the instance lazily on the first call.
    """
    global _llm_client_instance
    if _llm_client_instance is None:
        provider = settings.LLM_PROVIDER
        if provider == "openai":
            api_key, model = settings.OPENAI_API_KEY, settings.OPENAI_MODEL
        elif provider == "anthropic":
            api_key, model = settings.ANTHROPIC_API_KEY, settings.ANTHROPIC_MODEL
        elif provider == "gemini":
            api_key, model = settings.GEMINI_API_KEY, settings.GEMINI_MODEL
        else:
            api_key, model = settings.GROQ_API_KEY, settings.GROQ_MODEL

        _llm_client_instance = LangChainProvider(
            provider=provider,
            api_key=api_key,
            model=model,
        )
    return _llm_client_instance


def reset_llm_client(provider: str, api_key: str, model: str) -> LangChainProvider:
    """
    Replace the global singleton with a new provider/model/key combination.

    Called by the POST /llm-settings endpoint so all subsequent debate
    requests use the user-selected backend without a server restart.
    """
    global _llm_client_instance, _using_custom_key
    _llm_client_instance = LangChainProvider(
        provider=provider,
        api_key=api_key,
        model=model,
    )
    # B8 Fix: only flag custom key when the provider is NOT groq (which uses the server key)
    _using_custom_key = (provider != "groq")
    logger.info(
        "llm_client_switched",
        extra={"provider": provider, "model": model},
    )
    return _llm_client_instance


def get_active_provider_info() -> dict:
    """Return a snapshot of the current provider, model, and custom-key flag."""
    client = get_llm_client()
    return {
        "provider": client.provider,
        "model": client.model,
        "using_custom_key": _using_custom_key,
    }
