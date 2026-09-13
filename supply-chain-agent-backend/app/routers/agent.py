"""Agent endpoints.

``POST /agent/recover`` runs one observe → detect → investigate → optimize →
execute → verify pass and returns the explanation alongside the full reasoning
trace. ``GET /agent/tools`` lists the tools and the endpoints they wrap.
"""

from typing import Optional

from fastapi import APIRouter, Request

from app.agent.loop import MAX_REPLAN_CYCLES, run_recovery_agent
from app.agent.tools import tool_catalogue
from app.ratelimit import AGENT_LIMIT, limiter
from app.routers.deps import DbSession
from app.schemas.agent import AgentRunRequest, AgentRunResponse, ToolSpecRead
from app.security import WRITE_GUARD

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get(
    "/tools",
    response_model=list[ToolSpecRead],
    summary="List the agent's tools",
    description=(
        "Every tool the agent may call, with the backend endpoint it wraps. All "
        "cost, delivery and carbon arithmetic happens in ``optimize_recovery``; "
        "the agent itself only orchestrates."
    ),
)
def list_agent_tools() -> list[ToolSpecRead]:
    return [ToolSpecRead(**spec) for spec in tool_catalogue()]


@router.post(
    "/recover",
    response_model=AgentRunResponse,
    summary="Run one recovery pass",
    description=(
        "Observes demand, acts only when ``constraint_violated`` is true, "
        "investigates the available alternatives, asks the optimizer to rank "
        "them, executes the top-ranked action and verifies the result, "
        "replanning on failure up to a hard cap of "
        f"{MAX_REPLAN_CYCLES} cycles. Returns the natural-language explanation "
        "(generated from the recorded tool results only) plus the raw reasoning "
        "trace. Requires the API key and is rate limited, since each call can "
        "spend real LLM money."
    ),
    dependencies=WRITE_GUARD,
)
@limiter.limit(AGENT_LIMIT)
def run_agent(
    request: Request,
    db: DbSession,
    payload: Optional[AgentRunRequest] = None,
) -> AgentRunResponse:
    max_replans = (
        payload.max_replans
        if payload is not None and payload.max_replans is not None
        else MAX_REPLAN_CYCLES
    )
    run = run_recovery_agent(db, max_replans=max_replans)
    return AgentRunResponse.from_run(run)
