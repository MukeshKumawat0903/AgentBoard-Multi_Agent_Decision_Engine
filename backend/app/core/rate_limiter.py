"""
Shared rate-limiter singleton for use across FastAPI route decorators.

Built on ``slowapi`` (a Starlette-friendly wrapper around the ``limits``
library).  The limiter is keyed by the client's remote IP address, which
is suitable for development and single-instance deployments.

For production behind a reverse proxy, replace ``get_remote_address``
with a custom extractor that reads the ``X-Forwarded-For`` header.

Usage in routes::

    from app.core.rate_limiter import limiter

    @router.post("/debate/start")
    @limiter.limit("10/minute")
    async def start_debate(request: Request, ...):
        ...

Registration in main.py::

    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from app.core.rate_limiter import limiter

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
"""

from slowapi import Limiter  # type: ignore[import-untyped]
from slowapi.util import get_remote_address  # type: ignore[import-untyped]

limiter = Limiter(key_func=get_remote_address)
