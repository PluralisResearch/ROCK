"""Tests for the dashboard and new trace API endpoints."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rock.sdk.model.server.api.traces import traces_router
from rock.sdk.model.server.dashboard import dashboard_router
from rock.sdk.model.server.trace_store import TraceStore


def _make_trace(trace_id="t-1", user_id="alice", session_id="sess-1", status="success", **overrides):
    trace = {
        "trace_id": trace_id,
        "timestamp": "2026-03-08T10:00:00+00:00",
        "user_id": user_id,
        "session_id": session_id,
        "agent_type": "iflow",
        "model": "qwen",
        "latency_ms": 150.5,
        "status": status,
        "error": None,
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "request": {"model": "qwen", "messages": [{"role": "user", "content": "hello"}]},
        "response": {"id": "chat-1", "choices": []},
    }
    trace.update(overrides)
    return trace


@pytest.fixture
def app_with_store():
    """Create a test app with an in-memory trace store, trace routes, and dashboard."""
    app = FastAPI()
    app.include_router(traces_router)
    app.include_router(dashboard_router)
    store = TraceStore(":memory:")
    app.state.trace_store = store
    return app, store


@pytest.fixture
def app_without_store():
    """Create a test app with no trace store (disabled)."""
    app = FastAPI()
    app.include_router(traces_router)
    app.include_router(dashboard_router)
    return app


# --- Dashboard ---


@pytest.mark.asyncio
async def test_dashboard_returns_html(app_with_store):
    app, store = app_with_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "ROCK Gateway Dashboard" in resp.text
    assert "Chart.js" in resp.text or "chart.js" in resp.text


# --- /v1/traces/users ---


@pytest.mark.asyncio
async def test_users_endpoint_empty(app_with_store):
    app, store = app_with_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/users")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_users_endpoint_with_data(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice"))
    store.insert(_make_trace(trace_id="t-2", user_id="alice", latency_ms=200.0))
    store.insert(_make_trace(trace_id="t-3", user_id="bob"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/users")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # alice has more requests, should be first
    alice = next(u for u in data if u["user_id"] == "alice")
    assert alice["request_count"] == 2
    assert alice["total_tokens"] == 300  # 150 * 2
    bob = next(u for u in data if u["user_id"] == "bob")
    assert bob["request_count"] == 1


# --- /v1/traces/sessions ---


@pytest.mark.asyncio
async def test_sessions_endpoint_empty(app_with_store):
    app, store = app_with_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_sessions_endpoint_excludes_empty_session_id(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", session_id=""))
    store.insert(_make_trace(trace_id="t-2", session_id="sess-abc"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "sess-abc"


@pytest.mark.asyncio
async def test_sessions_endpoint_with_data(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice", session_id="sess-1", timestamp="2026-03-08T10:00:00"))
    store.insert(_make_trace(trace_id="t-2", user_id="alice", session_id="sess-1", timestamp="2026-03-08T10:05:00"))
    store.insert(_make_trace(trace_id="t-3", user_id="alice", session_id="sess-2", timestamp="2026-03-08T11:00:00"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    # sess-2 is more recent, should be first
    assert data[0]["session_id"] == "sess-2"
    assert data[0]["request_count"] == 1

    assert data[1]["session_id"] == "sess-1"
    assert data[1]["request_count"] == 2


@pytest.mark.asyncio
async def test_sessions_filtered_by_user(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice", session_id="sess-a"))
    store.insert(_make_trace(trace_id="t-2", user_id="bob", session_id="sess-b"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/sessions?user_id=alice")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["user_id"] == "alice"


# --- /v1/traces/timeline ---


@pytest.mark.asyncio
async def test_timeline_endpoint_empty(app_with_store):
    app, store = app_with_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/timeline")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_timeline_endpoint_hourly(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", timestamp="2026-03-08T10:00:00"))
    store.insert(_make_trace(trace_id="t-2", timestamp="2026-03-08T10:30:00"))
    store.insert(_make_trace(trace_id="t-3", timestamp="2026-03-08T11:00:00"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/timeline?interval=hour")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2  # 10:00 and 11:00 buckets
    assert data[0]["request_count"] == 2  # two traces in 10:00 hour
    assert data[1]["request_count"] == 1


@pytest.mark.asyncio
async def test_timeline_endpoint_daily(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", timestamp="2026-03-08T10:00:00"))
    store.insert(_make_trace(trace_id="t-2", timestamp="2026-03-09T10:00:00"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/timeline?interval=day")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["bucket"] == "2026-03-08"
    assert data[1]["bucket"] == "2026-03-09"


@pytest.mark.asyncio
async def test_timeline_with_user_filter(app_with_store):
    app, store = app_with_store
    store.insert(_make_trace(trace_id="t-1", user_id="alice", timestamp="2026-03-08T10:00:00"))
    store.insert(_make_trace(trace_id="t-2", user_id="bob", timestamp="2026-03-08T10:00:00"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/traces/timeline?user_id=alice")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["request_count"] == 1


# --- 503 when store disabled ---


@pytest.mark.asyncio
async def test_new_endpoints_503_when_store_disabled(app_without_store):
    app = app_without_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_users = await ac.get("/v1/traces/users")
        resp_sessions = await ac.get("/v1/traces/sessions")
        resp_timeline = await ac.get("/v1/traces/timeline")
    assert resp_users.status_code == 503
    assert resp_sessions.status_code == 503
    assert resp_timeline.status_code == 503
