"""
Unit tests for GroqClient (app/services/llm_client.py).

All tests mock the underlying httpx.AsyncClient so no real API calls
are made.  Tests cover:
  - Successful text / JSON responses
  - JSON parse failure → retry → success
  - JSON parse failure → retry → failure → LLMResponseError
  - HTTP 429 → backoff retry → LLMRateLimitError
  - HTTP 429 → backoff retry → success
  - HTTP 500 server error → LLMConnectionError
  - Network / timeout errors → LLMConnectionError
  - Singleton factory returns the same instance
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_client import GroqClient, get_llm_client
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_KEY  = "test-api-key"
_DUMMY_MODEL = "llama-3.3-70b-versatile"
_DUMMY_URL   = "https://api.groq.com/openai/v1"


def _make_client(monkeypatch=None) -> GroqClient:
    """Return a GroqClient with a mocked httpx.AsyncClient."""
    return GroqClient(api_key=_DUMMY_KEY, model=_DUMMY_MODEL, base_url=_DUMMY_URL)


def _ok_response(content: str) -> MagicMock:
    """Build a mock httpx Response for a successful chat-completion."""
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()  # no-op
    return resp


def _error_response(status_code: int, headers: dict | None = None) -> MagicMock:
    """Build a mock httpx Response for an error status code."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock(side_effect=Exception(f"HTTP {status_code}"))
    return resp


# ---------------------------------------------------------------------------
# chat() – plain text
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chat_returns_raw_text():
    """chat() should return the raw content string from the LLM."""
    client = _make_client()
    client._client.post = AsyncMock(return_value=_ok_response("Hello, world!"))

    result = await client.chat("You are helpful.", "Say hello.")
    assert result == "Hello, world!"


@pytest.mark.anyio
async def test_chat_sends_correct_payload():
    """chat() should include system+user messages and correct model."""
    client = _make_client()
    post_mock = AsyncMock(return_value=_ok_response("ok"))
    client._client.post = post_mock

    await client.chat("sys prompt", "user prompt", temperature=0.5)

    call_kwargs = post_mock.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload["model"] == _DUMMY_MODEL
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert payload["temperature"] == 0.5


# ---------------------------------------------------------------------------
# chat_json() – structured JSON output
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chat_json_returns_parsed_dict():
    """chat_json() should return a parsed Python dict."""
    client = _make_client()
    payload_str = json.dumps({"decision": "proceed", "confidence": 0.9})
    client._client.post = AsyncMock(return_value=_ok_response(payload_str))

    result = await client.chat_json("sys", "user")

    assert isinstance(result, dict)
    assert result["decision"] == "proceed"
    assert result["confidence"] == 0.9


@pytest.mark.anyio
async def test_chat_json_enforces_json_format():
    """chat_json() should add response_format and JSON enforcement to prompt."""
    client = _make_client()
    post_mock = AsyncMock(return_value=_ok_response('{"ok": true}'))
    client._client.post = post_mock

    await client.chat_json("base sys", "user task")

    payload = post_mock.call_args.kwargs.get("json") or post_mock.call_args.args[1]
    assert payload.get("response_format") == {"type": "json_object"}
    assert "JSON" in payload["messages"][0]["content"]


@pytest.mark.anyio
async def test_chat_json_retries_on_invalid_json_and_succeeds():
    """
    chat_json() – first LLM response is invalid JSON.
    Second call (retry) returns valid JSON → should succeed.
    """
    client = _make_client()
    bad_response  = _ok_response("This is not JSON at all!")
    good_response = _ok_response('{"result": "success"}')
    client._client.post = AsyncMock(side_effect=[bad_response, good_response])

    result = await client.chat_json("sys", "user")

    assert result == {"result": "success"}


@pytest.mark.anyio
async def test_chat_json_raises_after_failed_retry():
    """
    chat_json() – both responses are invalid JSON.
    Should raise LLMResponseError after the retry.
    """
    client = _make_client()
    bad  = _ok_response("not json {{}")
    bad2 = _ok_response("still not json")
    client._client.post = AsyncMock(side_effect=[bad, bad2])

    with pytest.raises(LLMResponseError, match="unparseable JSON"):
        await client.chat_json("sys", "user")


# ---------------------------------------------------------------------------
# Rate limiting – HTTP 429
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_rate_limit_raises_after_max_retries():
    """
    HTTP 429 on all attempts should raise LLMRateLimitError.
    Retries = _MAX_RETRIES(2) → total 3 attempts, all 429.
    """
    client = _make_client()
    rate_limited = _error_response(429, headers={"retry-after": "0.01"})
    client._client.post = AsyncMock(return_value=rate_limited)

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMRateLimitError):
            await client.chat("sys", "user")


@pytest.mark.anyio
async def test_rate_limit_succeeds_after_one_retry():
    """
    First response is 429, second is 200 → should succeed and return text.
    """
    client = _make_client()
    rate_limited = _error_response(429, headers={"retry-after": "0.01"})
    ok = _ok_response("recovered!")
    client._client.post = AsyncMock(side_effect=[rate_limited, ok])

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client.chat("sys", "user")

    assert result == "recovered!"


# ---------------------------------------------------------------------------
# Server errors – HTTP 5xx
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_server_error_raises_connection_error():
    """Persistent HTTP 500 should raise LLMConnectionError."""
    client = _make_client()
    client._client.post = AsyncMock(return_value=_error_response(500))

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMConnectionError, match="server error"):
            await client.chat("sys", "user")


@pytest.mark.anyio
async def test_server_error_recovers_on_retry():
    """HTTP 500 once, then 200 → should succeed."""
    client = _make_client()
    client._client.post = AsyncMock(
        side_effect=[_error_response(500), _ok_response("back online")]
    )

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client.chat("sys", "user")

    assert result == "back online"


# ---------------------------------------------------------------------------
# Network errors
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_network_error_raises_connection_error():
    """httpx.ConnectError should be translated to LLMConnectionError."""
    import httpx

    client = _make_client()
    client._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMConnectionError, match="Network error"):
            await client.chat("sys", "user")


@pytest.mark.anyio
async def test_timeout_raises_connection_error():
    """httpx.TimeoutException should be translated to LLMConnectionError."""
    import httpx

    client = _make_client()
    client._client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch("app.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMConnectionError):
            await client.chat("sys", "user")


# ---------------------------------------------------------------------------
# Malformed response structure
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_missing_choices_raises_response_error():
    """If the GROQ response lacks the expected structure, raise LLMResponseError."""
    client = _make_client()
    bad_struct = MagicMock()
    bad_struct.status_code = 200
    bad_struct.headers = {}
    bad_struct.raise_for_status = MagicMock()
    bad_struct.json.return_value = {"unexpected_key": "value"}  # no "choices"
    client._client.post = AsyncMock(return_value=bad_struct)

    with pytest.raises(LLMResponseError, match="response structure"):
        await client.chat("sys", "user")


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

def test_get_llm_client_returns_same_instance():
    """get_llm_client() should return the same singleton on repeated calls."""
    import app.services.llm_client as llm_module

    # Reset the singleton so the test is isolated
    llm_module._llm_client_instance = None

    first  = get_llm_client()
    second = get_llm_client()
    assert first is second

    # Clean up for other tests
    llm_module._llm_client_instance = None
