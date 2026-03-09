import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from functools import wraps

from fastapi.responses import JSONResponse

from rock.sdk.model.server.config import TRAJ_FILE

# Module-level override for traj file path
_traj_file_override: str | None = None


def init_traj_file(path: str):
    """Set a custom traj file path, overriding the default."""
    global _traj_file_override
    if path:
        _traj_file_override = path


def _write_traj(data: dict):
    """Write traj data to file in JSONL format."""
    from rock import env_vars

    traj_path = _traj_file_override or TRAJ_FILE
    append = env_vars.ROCK_MODEL_SERVICE_TRAJ_APPEND_MODE
    if traj_path:
        os.makedirs(os.path.dirname(traj_path), exist_ok=True)
        mode = "a" if append else "w"
        with open(traj_path, mode, encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def _write_to_store(trace_data: dict):
    """Write trace data to SQLite store if available."""
    try:
        from rock.sdk.model.server.trace_store import get_store

        store = get_store()
        if store is not None:
            store.insert(trace_data)
    except Exception:
        pass


def record_traj(func: Callable):
    """Decorator to record chat completions input/output as traj with enhanced metadata."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract body and request from args/kwargs
        body = args[0] if args else kwargs.get("body")
        request = args[1] if len(args) > 1 else kwargs.get("request")

        # Extract metadata from headers
        user_id = "anonymous"
        session_id = ""
        agent_type = ""
        if request is not None:
            user_id = request.headers.get("x-rock-user-id", "")
            if not user_id:
                auth_header = request.headers.get("authorization", "")
                if auth_header.lower().startswith("bearer "):
                    user_id = auth_header[7:].strip()
            if not user_id:
                user_id = request.headers.get("x-api-key", "")
            if not user_id:
                user_id = "anonymous"
            session_id = request.headers.get("x-rock-session-id", "")
            agent_type = request.headers.get("x-rock-agent-type", "")

        trace_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        model = body.get("model", "") if isinstance(body, dict) else ""

        start = time.monotonic()
        error_msg = None
        status = "success"
        result = None

        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            status = "error"
            error_msg = str(e)
            raise
        finally:
            latency_ms = round((time.monotonic() - start) * 1000, 2)

            # Extract response data
            response_data = None
            if result is not None:
                if isinstance(result, JSONResponse):
                    response_data = json.loads(result.body)
                else:
                    response_data = result

            # Extract token usage
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            if isinstance(response_data, dict):
                usage = response_data.get("usage", {})
                if usage:
                    token_usage = {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }

            trace_data = {
                "trace_id": trace_id,
                "timestamp": timestamp,
                "user_id": user_id,
                "session_id": session_id,
                "agent_type": agent_type,
                "model": model,
                "latency_ms": latency_ms,
                "status": status,
                "error": error_msg,
                "token_usage": token_usage,
                "request": body,
                "response": response_data,
            }

            _write_traj(trace_data)
            _write_to_store(trace_data)

    return wrapper
