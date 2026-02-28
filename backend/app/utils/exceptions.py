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
