"""Tests for the LangChainProvider adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.llm_client import LangChainProvider, get_llm_client
from app.utils.exceptions import LLMConnectionError, LLMResponseError

_DUMMY_KEY = "test-api-key"
_DUMMY_MODEL = "llama-3.3-70b-versatile"


class DemoSchema(BaseModel):
    answer: str
    confidence: float


def _make_provider(fake_llm: MagicMock | None = None) -> tuple[LangChainProvider, MagicMock]:
    llm = fake_llm or MagicMock()
    with patch.object(LangChainProvider, "_build_llm", return_value=llm):
        provider = LangChainProvider(api_key=_DUMMY_KEY, model=_DUMMY_MODEL)
    return provider, llm


@pytest.mark.anyio
async def test_chat_returns_raw_text():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=MagicMock(content="Hello, world!"))
    llm.bind.return_value = bound

    result = await provider.chat("You are helpful.", "Say hello.")

    assert result == "Hello, world!"
    llm.bind.assert_called_once_with(temperature=0.7, max_tokens=2048)


@pytest.mark.anyio
async def test_chat_builds_messages_from_prompts():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
    llm.bind.return_value = bound

    await provider.chat("sys prompt", "user prompt", temperature=0.5, max_tokens=512)

    llm.bind.assert_called_once_with(temperature=0.5, max_tokens=512)
    messages = bound.ainvoke.call_args.args[0]
    assert messages[0].content == "sys prompt"
    assert messages[1].content == "user prompt"


@pytest.mark.anyio
async def test_chat_json_returns_parsed_dict():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=MagicMock(content='{"decision":"proceed","confidence":0.9}'))
    llm.bind.return_value = bound

    result = await provider.chat_json("sys", "user")

    assert result == {"decision": "proceed", "confidence": 0.9}


@pytest.mark.anyio
async def test_chat_json_raises_on_invalid_json():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=MagicMock(content="not json"))
    llm.bind.return_value = bound

    with pytest.raises(LLMResponseError, match="unparseable JSON"):
        await provider.chat_json("sys", "user")


@pytest.mark.anyio
async def test_ainvoke_structured_returns_validated_model():
    provider, llm = _make_provider()
    bound = MagicMock()
    structured = MagicMock()
    retried = MagicMock()
    retried.ainvoke = AsyncMock(return_value=DemoSchema(answer="Proceed", confidence=0.82))
    structured.with_retry.return_value = retried
    bound.with_structured_output.return_value = structured
    llm.bind.return_value = bound

    result = await provider.ainvoke_structured(DemoSchema, system_prompt="sys", user_prompt="user")

    assert isinstance(result, DemoSchema)
    assert result.answer == "Proceed"
    bound.with_structured_output.assert_called_once_with(DemoSchema)


@pytest.mark.anyio
async def test_ainvoke_structured_wraps_failures_as_response_errors():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.with_structured_output.side_effect = RuntimeError("schema bind failed")
    llm.bind.return_value = bound

    with pytest.raises(LLMResponseError, match="Structured output failed"):
        await provider.ainvoke_structured(DemoSchema, system_prompt="sys", user_prompt="user")


@pytest.mark.anyio
async def test_chat_wraps_transport_errors_as_connection_errors():
    provider, llm = _make_provider()
    bound = MagicMock()
    bound.ainvoke = AsyncMock(side_effect=RuntimeError("network down"))
    llm.bind.return_value = bound

    with pytest.raises(LLMConnectionError, match="LLM chat call failed"):
        await provider.chat("sys", "user")


def test_get_llm_client_returns_same_instance():
    import app.services.llm_client as llm_module

    fake_llm = MagicMock()
    llm_module._llm_client_instance = None
    with patch.object(LangChainProvider, "_build_llm", return_value=fake_llm):
        first = get_llm_client()
        second = get_llm_client()

    assert first is second
    llm_module._llm_client_instance = None
