"""Structured audit logging helpers for mutation endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request


audit_logger = logging.getLogger("agentboard.audit")


def audit_event(
    action: str,
    *,
    outcome: str,
    request: Request | None = None,
    thread_id: str | None = None,
    detail: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured audit record for a state-changing operation."""
    client_ip = None
    if request is not None and request.client is not None:
        client_ip = request.client.host

    extra = {
        "action": action,
        "outcome": outcome,
        "thread_id": thread_id,
        "client_ip": client_ip,
        "detail": detail,
    }
    extra.update(fields)
    audit_logger.info("audit_event", extra=extra)