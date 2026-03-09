"""Tests for the SQLite TraceStore."""

import pytest

from rock.sdk.model.server.trace_store import TraceStore, get_store, init_store


def _make_trace(trace_id="t-1", user_id="alice", model="qwen", status="success", **overrides):
    """Helper to create a trace data dict."""
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
        "response": {
            "id": "chat-1",
            "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        },
    }
    trace.update(overrides)
    return trace


@pytest.fixture
def store():
    return TraceStore(":memory:")


class TestTraceStoreInsertAndGet:
    def test_insert_and_get_by_id(self, store):
        trace = _make_trace()
        store.insert(trace)
        result = store.get_by_id("t-1")
        assert result is not None
        assert result["trace_id"] == "t-1"
        assert result["user_id"] == "alice"
        assert result["model"] == "qwen"
        assert result["latency_ms"] == 150.5
        assert result["token_usage"]["prompt_tokens"] == 100
        assert result["request_body"]["model"] == "qwen"
        assert result["response_body"]["id"] == "chat-1"

    def test_duplicate_trace_id_ignored(self, store):
        trace = _make_trace()
        store.insert(trace)
        # Insert again with same trace_id — should be silently ignored (INSERT OR IGNORE)
        store.insert(trace)
        results = store.query()
        assert len(results) == 1

    def test_get_by_id_not_found(self, store):
        result = store.get_by_id("nonexistent")
        assert result is None


class TestTraceStoreQuery:
    def test_query_no_filters(self, store):
        store.insert(_make_trace(trace_id="t-1"))
        store.insert(_make_trace(trace_id="t-2", user_id="bob"))
        results = store.query()
        assert len(results) == 2

    def test_query_by_user_id(self, store):
        store.insert(_make_trace(trace_id="t-1", user_id="alice"))
        store.insert(_make_trace(trace_id="t-2", user_id="bob"))
        results = store.query(user_id="alice")
        assert len(results) == 1
        assert results[0]["user_id"] == "alice"

    def test_query_by_model(self, store):
        store.insert(_make_trace(trace_id="t-1", model="qwen"))
        store.insert(_make_trace(trace_id="t-2", model="gpt-4"))
        results = store.query(model="qwen")
        assert len(results) == 1
        assert results[0]["model"] == "qwen"

    def test_query_by_status(self, store):
        store.insert(_make_trace(trace_id="t-1", status="success"))
        store.insert(_make_trace(trace_id="t-2", status="error", error="timeout"))
        results = store.query(status="error")
        assert len(results) == 1
        assert results[0]["status"] == "error"

    def test_query_by_date_range(self, store):
        store.insert(_make_trace(trace_id="t-1", timestamp="2026-03-07T10:00:00+00:00"))
        store.insert(_make_trace(trace_id="t-2", timestamp="2026-03-08T10:00:00+00:00"))
        store.insert(_make_trace(trace_id="t-3", timestamp="2026-03-09T10:00:00+00:00"))
        results = store.query(start="2026-03-08T00:00:00+00:00", end="2026-03-08T23:59:59+00:00")
        assert len(results) == 1
        assert results[0]["trace_id"] == "t-2"

    def test_query_pagination(self, store):
        for i in range(5):
            store.insert(_make_trace(trace_id=f"t-{i}", timestamp=f"2026-03-08T10:0{i}:00+00:00"))
        results = store.query(limit=2, offset=0)
        assert len(results) == 2
        results2 = store.query(limit=2, offset=2)
        assert len(results2) == 2
        results3 = store.query(limit=2, offset=4)
        assert len(results3) == 1


class TestTraceStoreStats:
    def test_stats_unfiltered(self, store):
        store.insert(_make_trace(trace_id="t-1", status="success", latency_ms=100.0))
        store.insert(_make_trace(trace_id="t-2", status="success", latency_ms=200.0))
        store.insert(_make_trace(trace_id="t-3", status="error", latency_ms=50.0, error="fail"))
        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["success_count"] == 2
        assert stats["error_count"] == 1
        assert stats["min_latency_ms"] == 50.0
        assert stats["max_latency_ms"] == 200.0
        assert stats["total_prompt_tokens"] == 300  # 100 * 3

    def test_stats_filtered_by_user(self, store):
        store.insert(_make_trace(trace_id="t-1", user_id="alice"))
        store.insert(_make_trace(trace_id="t-2", user_id="bob"))
        stats = store.get_stats(user_id="alice")
        assert stats["total"] == 1

    def test_stats_empty(self, store):
        stats = store.get_stats()
        assert stats["total"] == 0
        assert stats["avg_latency_ms"] == 0


class TestTraceStoreSingleton:
    def test_init_store_and_get_store(self):
        store = init_store(":memory:")
        assert get_store() is store
