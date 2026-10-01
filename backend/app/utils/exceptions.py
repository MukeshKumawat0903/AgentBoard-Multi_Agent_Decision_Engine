"""
Custom exception classes for AgentBoard.

Provides structured error types for LLM interactions
and debate engine failures.
"""


class AgentBoardError(Exception):
    """Base exception for all AgentBoard errors."""
    pass


class LLMResponseError(AgentBoardError):
    """Raised when the LLM returns unparseable or unexpected response."""
    pass


class LLMConnectionError(AgentBoardError):
    """Raised when unable to connect to the LLM API."""
    pass


class LLMRateLimitError(AgentBoardError):
    """Raised when the LLM API returns a 429 rate limit response."""
    pass


class DebateError(AgentBoardError):
    """Raised when the debate engine encounters an unrecoverable error."""
    pass


# User-facing wording per error class. Raw exception text can carry provider
# internals (organisation IDs, request payloads, quotas) or file paths, so it is
# logged server-side and never sent to the browser.
_PUBLIC_ERROR_MESSAGES: tuple[tuple[type[BaseException], str], ...] = (
    (LLMRateLimitError, "The AI provider rate-limited the debate. Please wait a moment and try again."),
    (LLMConnectionError, "Could not connect to the AI provider."),
    (LLMResponseError, "The AI model failed to produce a valid response."),
    (DebateError, "The debate engine encountered an unrecoverable error."),
)


def public_error_message(exc: BaseException) -> str:
    """Return a safe, user-facing description of ``exc``."""
    for exc_type, message in _PUBLIC_ERROR_MESSAGES:
        if isinstance(exc, exc_type):
            return message
    return "The debate engine hit an unexpected error."
