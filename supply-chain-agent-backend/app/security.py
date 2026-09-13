"""API-key authentication for state-changing endpoints.

Every mutating request — the action, disruption, agent and admin routes plus the
CRUD writes — must present the server's API key in the ``X-API-Key`` header.
Read-only ``GET`` endpoints deliberately stay open so the demo dashboard can
poll them without holding a key; they are still rate-limited (see
``app.ratelimit``).

The key is read from the ``API_KEY`` environment variable and compared in
constant time. When it is unset the app runs in development demo mode with
writes open and logs a warning at startup; outside development an unset key is a
hard configuration error (``Settings``), so a shared deployment cannot start
unauthenticated by accident.

Attach :data:`WRITE_GUARD` to any route that changes state::

    @router.post("", dependencies=WRITE_GUARD, ...)
"""

import hmac
import logging
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Header a caller presents the key in.
API_KEY_HEADER = "X-API-Key"

api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,  # handled here, so an unset key can mean "demo mode"
    description="Server API key. Required on every state-changing endpoint.",
)


def require_api_key(
    presented: Annotated[Optional[str], Security(api_key_header)],
) -> None:
    """Reject a state-changing request that does not carry the configured key."""
    expected = get_settings().api_key
    if not expected:
        # Development demo mode: no key configured, writes stay open.
        return
    if presented is None or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"A valid {API_KEY_HEADER} header is required for this endpoint",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )


#: Attach to every mutating route (``dependencies=WRITE_GUARD``) or router.
WRITE_GUARD = [Depends(require_api_key)]


def warn_if_writes_are_open() -> bool:
    """Log a startup warning when mutating endpoints are unauthenticated.

    Returns whether writes are open, which is also what ``GET /health`` reports
    so the situation is visible to an operator, not just to the log.
    """
    if get_settings().api_key:
        return False
    logger.warning(
        "API_KEY is not set: state-changing endpoints are UNAUTHENTICATED. "
        "Set API_KEY before exposing this service."
    )
    return True
