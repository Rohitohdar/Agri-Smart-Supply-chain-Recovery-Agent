"""Rate limiting for every endpoint.

Read-only endpoints are open, but open is not the same as unmetered: a dashboard
behind a public URL is an amplification target, and the agent trigger is worse
still because each call can spend real LLM money. ``slowapi`` applies a default
limit to every request and the two caller-driven compute endpoints get a tighter
one of their own.

Limits are configurable (``RATE_LIMIT_*``) and the whole limiter can be switched
off with ``RATE_LIMIT_ENABLED=false``, which is what the test suite does so its
hundreds of requests do not collide with each other. A tripped limit answers
``429`` with the project's usual ``reason`` code.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

#: Keyed on the peer address. Behind a reverse proxy every caller shares one
#: bucket unless the proxy is trusted to rewrite the client address.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)

#: Tighter per-route limits. A call to either endpoint can cost real money.
AGENT_LIMIT = settings.rate_limit_agent
OPTIMIZE_LIMIT = settings.rate_limit_optimize


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Answer a tripped limit the same way the rest of the API reports refusals."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}", "reason": "rate_limited"},
    )


def install_rate_limiting(app: FastAPI) -> None:
    """Attach the limiter, its middleware and its handler to ``app``.

    Must run before the app starts serving: ``add_middleware`` is not allowed
    afterwards.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
