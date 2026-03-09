"""Tests for the Trace Query API endpoints."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rock.sdk.model.server.api.traces import traces_router
from rock.sdk.model.server.trace_store import TraceStore


def _make_trace(trace_id="t-1", user_id="alice", model="qwen", status="success", **overrides):
    trace = {
        "trace_id": trace_id,
        "timestamp": "2026-03-08T10:00:00+00:00",
        "user_id": user_id,
        "session_id": "sess-1",
        "agent_type": "iflow",
        "model": model,
        "latency_ms": 150.5,
        "status": status,
        "error": None,
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "request": {"model": model, "messages": [{"role": "user", "content": "hello"}]},
        "response": {"id": "chat-1", "choices": []},
    }
    trace.update(overrides)
    return trace


@pytest.fixture
def app_with_store():
    """Create a test app with an in-memory trace store."""
    app = FastAPI()
    app.include_router(traces_router)
    store = TraceStore(":memory:")
    app.state.trace_store = store
    return app, store


@pytest.fixture
def app_without_store():
    """Create a test app with no trace store (disabled)."""
    app = FastAPI()
    app.include_router(traces_router)
    return app


@pytest.mark.asyncio
async def test_list_traces_empty(app_with_store):
    app, store = app_with_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces")
    assert resp.status_code == 200
    data = resp.json()
    assert data["traces"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_traces_with_data(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1"))
    store.insert(_make_trace(trace_id="t-2", user_id="bob"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_list_traces_filtered_by_user_id(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice"))
    store.insert(_make_trace(trace_id="t-2", user_id="bob"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces?user_id=alice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["traces"][0]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_list_traces_filtered_by_status(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", status="success"))
    store.insert(_make_trace(trace_id="t-2", status="error", error="fail"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces?status=error")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["traces"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_list_traces_pagination(app_with_store):
    app, store = app_with_store
    for i in range(5):
        store.insert(_make_trace(trace_id=f"t-{i}", timestamp=f"2026-03-08T10:0{i}:00+00:00"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["traces"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_get_trace_by_id_found(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-abc"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/t-abc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace_id"] == "t-abc"
    assert data["request_body"] is not None
    assert data["response_body"] is not None


@pytest.mark.asyncio
async def test_get_trace_by_id_not_found(app_with_store):
    app, store = app_with_store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stats_unfiltered(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", status="success", latency_ms=100.0))
    store.insert(_make_trace(trace_id="t-2", status="error", latency_ms=200.0, error="fail"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["success_count"] == 1
    assert data["error_count"] == 1
    assert data["min_latency_ms"] == 100.0
    assert data["max_latency_ms"] == 200.0


@pytest.mark.asyncio
async def test_stats_filtered(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice"))
    store.insert(_make_trace(trace_id="t-2", user_id="bob"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/stats?user_id=alice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_store_disabled_returns_503(app_without_store):
    app = app_without_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_list = await ac.get("/v1/traces")
        resp_stats = await ac.get("/v1/traces/stats")
        resp_detail = await ac.get("/v1/traces/some-id")
    assert resp_list.status_code == 503
    assert resp_stats.status_code == 503
    assert resp_detail.status_code == 503
