"""Guard for administrative endpoints.

Switching the server-wide LLM provider, clearing agent memory and deleting
knowledge-base documents affect every user of the deployment, so they are
restricted to holders of ``ADMIN_API_TOKEN`` (sent as ``X-Admin-Token``).

Without a configured token the actions stay open in development (single-user
local runs) but are refused in production.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.core.config import settings
from app.schemas.api_models import ErrorResponse


def admin_token_required() -> bool:
    """Whether clients must present an admin token for administrative actions."""
    return bool(settings.ADMIN_API_TOKEN) or settings.APP_ENV == "production"


async def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """FastAPI dependency: allow the request only for an administrator."""
    expected = settings.ADMIN_API_TOKEN
    if not expected:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=403,
                detail=ErrorResponse(
                    error="admin_disabled",
                    detail="Administrative actions are disabled: set ADMIN_API_TOKEN on the server.",
                ).model_dump(),
            )
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail=ErrorResponse(
                error="admin_token_required",
                detail="A valid admin token is required for this action.",
            ).model_dump(),
        )
