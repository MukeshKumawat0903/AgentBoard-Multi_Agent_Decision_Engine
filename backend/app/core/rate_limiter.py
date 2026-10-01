"""
Shared rate-limiter singleton for use across FastAPI route decorators.

Built on ``slowapi`` (a Starlette-friendly wrapper around the ``limits``
library).  Requests are keyed by the *client's* IP address.

Browsers reach the API through the Next.js proxy (and often an edge proxy in
front of it), so the TCP peer is the proxy, not the user. When the peer is one
of ``settings.TRUSTED_PROXY_IPS``, the client address is taken from
``X-Forwarded-For`` instead — otherwise every user would share one bucket.

Usage in routes::

    from app.core.rate_limiter import limiter

    @router.post("/debate/start")
    @limiter.limit("10/minute")
    async def start_debate(request: Request, ...):
        ...
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from slowapi import Limiter  # type: ignore[import-untyped]
from starlette.requests import Request

from app.core.config import settings

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple[_Network, ...]:
    networks: list[_Network] = []
    for item in spec.split(","):
        item = item.strip()
        if item:
            networks.append(ipaddress.ip_network(item, strict=False))
    return tuple(networks)


def _is_trusted_proxy(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _trusted_networks(settings.TRUSTED_PROXY_IPS))


def client_ip(request: Request) -> str:
    """Best-effort address of the end user who sent ``request``.

    The forwarded address is only believed when the direct peer is a trusted
    proxy, and the right-most hop is used: it is the one the nearest proxy
    added, whereas earlier entries can be supplied by the client itself.
    """
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    if not hops:
        return peer
    try:
        return str(ipaddress.ip_address(hops[-1]))
    except ValueError:
        return peer


limiter = Limiter(key_func=client_ip)
