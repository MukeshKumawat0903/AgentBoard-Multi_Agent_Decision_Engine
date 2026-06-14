"""Per-request logging context helpers."""

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind the current request ID to the active context."""
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    """Return the request ID for the current execution context."""
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request ID context."""
    _request_id.reset(token)
