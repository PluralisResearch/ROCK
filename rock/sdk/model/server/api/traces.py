"""Trace query API for the ROCK Model Gateway."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

traces_router = APIRouter()


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TraceSummary(BaseModel):
    trace_id: str
    timestamp: str
    user_id: str
    session_id: str
    agent_type: str
    model: str
    latency_ms: float
    status: str
    error: str | None = None
    token_usage: TokenUsage


class TraceResponse(TraceSummary):
    request_body: dict | list | None = None
    response_body: dict | list | None = None


class TraceListResponse(BaseModel):
    traces: list[TraceSummary]
    total: int
    limit: int
    offset: int


class TraceStatsResponse(BaseModel):
    total: int
    success_count: int
    error_count: int
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int


def _get_store_or_503(request: Request):
    """Get the trace store from app state or raise 503."""
    store = getattr(request.app.state, "trace_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Trace store is not enabled")
    return store


@traces_router.get("/v1/traces/stats", response_model=TraceStatsResponse)
async def get_trace_stats(
    request: Request,
    user_id: str | None = Query(default=None),
    model: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Get aggregate trace statistics."""
    store = _get_store_or_503(request)
    stats = await asyncio.to_thread(store.get_stats, user_id=user_id, model=model, start=start, end=end)
    return TraceStatsResponse(**stats)


@traces_router.get("/v1/traces", response_model=TraceListResponse)
async def list_traces(
    request: Request,
    user_id: str | None = Query(default=None),
    model: str | None = Query(default=None),
    status: str | None = Query(default=None),
    agent_type: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List traces with optional filters."""
    store = _get_store_or_503(request)
    traces = await asyncio.to_thread(
        store.query,
        user_id=user_id,
        model=model,
        status=status,
        agent_type=agent_type,
        session_id=session_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    # Convert rows to summaries (exclude request/response bodies)
    summaries = []
    for t in traces:
        summaries.append(
            TraceSummary(
                trace_id=t["trace_id"],
                timestamp=t["timestamp"],
                user_id=t["user_id"],
                session_id=t["session_id"],
                agent_type=t["agent_type"],
                model=t["model"],
                latency_ms=t["latency_ms"],
                status=t["status"],
                error=t.get("error"),
                token_usage=TokenUsage(**t["token_usage"]),
            )
        )
    return TraceListResponse(traces=summaries, total=len(summaries), limit=limit, offset=offset)


@traces_router.get("/v1/traces/{trace_id}", response_model=TraceResponse)
async def get_trace(request: Request, trace_id: str):
    """Get a single trace by ID with full request/response bodies."""
    store = _get_store_or_503(request)
    trace = await asyncio.to_thread(store.get_by_id, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return TraceResponse(
        trace_id=trace["trace_id"],
        timestamp=trace["timestamp"],
        user_id=trace["user_id"],
        session_id=trace["session_id"],
        agent_type=trace["agent_type"],
        model=trace["model"],
        latency_ms=trace["latency_ms"],
        status=trace["status"],
        error=trace.get("error"),
        token_usage=TokenUsage(**trace["token_usage"]),
        request_body=trace.get("request_body"),
        response_body=trace.get("response_body"),
    )
