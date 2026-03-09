"""Tests for the enhanced record_traj decorator."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from rock.sdk.model.server.utils import record_traj


def _make_request(headers=None):
    """Create a mock FastAPI Request with given headers."""
    mock = MagicMock(spec=Request)
    _headers = {"x-rock-user-id": "test-user", "x-rock-session-id": "sess-1", "x-rock-agent-type": "iflow"}
    if headers:
        _headers.update(headers)
    mock.headers = _headers
    return mock


@pytest.mark.asyncio
async def test_metadata_captured():
    """Test that trace_id, timestamp, user_id, latency_ms, model, status are captured."""
    body = {"model": "qwen", "messages": []}
    request = _make_request()

    @record_traj
    async def handler(body, request):
        return {
            "id": "chat-1",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        assert mock_write.called
        trace = mock_write.call_args[0][0]
        assert "trace_id" in trace
        assert "timestamp" in trace
        assert trace["user_id"] == "test-user"
        assert trace["model"] == "qwen"
        assert trace["status"] == "success"
        assert trace["latency_ms"] >= 0
        assert trace["error"] is None


@pytest.mark.asyncio
async def test_header_extraction_defaults_to_anonymous():
    """Test that missing X-Rock-User-Id defaults to 'anonymous'."""
    body = {"model": "qwen", "messages": []}
    request = MagicMock(spec=Request)
    request.headers = {}  # No custom headers

    @record_traj
    async def handler(body, request):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["user_id"] == "anonymous"
        assert trace["session_id"] == ""
        assert trace["agent_type"] == ""


@pytest.mark.asyncio
async def test_token_usage_extraction():
    """Test token usage is extracted from response."""
    body = {"model": "qwen", "messages": []}
    request = _make_request()

    @record_traj
    async def handler(body, request):
        return {
            "id": "chat-1",
            "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["token_usage"]["prompt_tokens"] == 100
        assert trace["token_usage"]["completion_tokens"] == 50
        assert trace["token_usage"]["total_tokens"] == 150


@pytest.mark.asyncio
async def test_error_path_capture():
    """Test that exceptions are captured as status='error' and re-raised."""
    body = {"model": "qwen", "messages": []}
    request = _make_request()

    @record_traj
    async def handler(body, request):
        raise ValueError("something broke")

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        with pytest.raises(ValueError, match="something broke"):
            await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["status"] == "error"
        assert trace["error"] == "something broke"
        assert trace["response"] is None


@pytest.mark.asyncio
async def test_json_response_handling():
    """Test that JSONResponse bodies are properly parsed."""
    body = {"model": "qwen", "messages": []}
    request = _make_request()

    @record_traj
    async def handler(body, request):
        return JSONResponse(content={"id": "chat-1", "choices": []})

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["response"]["id"] == "chat-1"


@pytest.mark.asyncio
async def test_store_integration():
    """Test that _write_to_store is called with trace data."""
    body = {"model": "qwen", "messages": []}
    request = _make_request()

    @record_traj
    async def handler(body, request):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj"),
        patch("rock.sdk.model.server.utils._write_to_store") as mock_store,
    ):
        await handler(body, request)
        assert mock_store.called
        trace = mock_store.call_args[0][0]
        assert trace["trace_id"]
        assert trace["user_id"] == "test-user"


@pytest.mark.asyncio
async def test_backward_compatibility_no_request():
    """Test decorator works when request arg is missing (backward compat)."""
    body = {"model": "qwen", "messages": []}

    @record_traj
    async def handler(body):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body)
        trace = mock_write.call_args[0][0]
        assert trace["user_id"] == "anonymous"


@pytest.mark.asyncio
async def test_user_id_from_authorization_bearer():
    """Test that user_id is extracted from Authorization: Bearer header."""
    body = {"model": "qwen", "messages": []}
    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer Gayal"}

    @record_traj
    async def handler(body, request):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["user_id"] == "Gayal"


@pytest.mark.asyncio
async def test_x_rock_user_id_takes_priority():
    """Test that x-rock-user-id takes priority over Authorization header."""
    body = {"model": "qwen", "messages": []}
    request = MagicMock(spec=Request)
    request.headers = {"x-rock-user-id": "custom-user", "authorization": "Bearer Gayal"}

    @record_traj
    async def handler(body, request):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["user_id"] == "custom-user"


@pytest.mark.asyncio
async def test_user_id_from_x_api_key():
    """Test that user_id falls back to x-api-key header."""
    body = {"model": "qwen", "messages": []}
    request = MagicMock(spec=Request)
    request.headers = {"x-api-key": "api-key-user"}

    @record_traj
    async def handler(body, request):
        return {"id": "chat-1", "choices": []}

    with (
        patch("rock.sdk.model.server.utils._write_traj") as mock_write,
        patch("rock.sdk.model.server.utils._write_to_store"),
    ):
        await handler(body, request)
        trace = mock_write.call_args[0][0]
        assert trace["user_id"] == "api-key-user"
