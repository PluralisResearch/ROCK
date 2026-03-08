# Plan: Central Model Gateway for Coding Agents with Open Models

## Goal

Engineers use a coding agent CLI (iflow/similar) locally on their real repos.
Open models (GLM-5, MiniMax, etc.) are hosted via vLLM on a GPU server.
All LLM calls are traced centrally with rich metadata (who, when, what model, success/fail).

## Architecture

```
Engineer's laptop                    GPU Server
┌────────────────┐                  ┌──────────────────────────────────┐
│ iflow CLI      │                  │                                  │
│ (works on real │── /v1/chat/──>   │  ROCK Model Gateway (:8080)      │
│  local files)  │   completions    │  (trace logging + routing)       │
└────────────────┘                  │       │               │          │
                                    │  ┌────▼─────┐  ┌─────▼───────┐  │
                                    │  │ vLLM     │  │ vLLM        │  │
                                    │  │ GLM-5    │  │ MiniMax     │  │
                                    │  │ :8001    │  │ :8002       │  │
                                    │  └──────────┘  └─────────────┘  │
                                    └──────────────────────────────────┘
```

---

## Phase 1: vLLM Model Hosting

> Nothing to code — just deployment configs.

### What to download / install on GPU server

| Item | Command | Notes |
|------|---------|-------|
| Docker + NVIDIA Container Toolkit | [nvidia docs](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) | Required for GPU passthrough |
| vLLM Docker image | `docker pull vllm/vllm-openai:latest` | ~8GB, includes CUDA runtime |
| Model weights (auto-downloaded) | Pulled by vLLM on first start via HuggingFace | Set `HF_TOKEN` env var if gated model |

### What to create

**File: `examples/agents/open_model_gateway/vllm/docker-compose.yaml`**

```yaml
services:
  vllm-glm5:
    image: vllm/vllm-openai:latest
    command: >
      --model THUDM/glm-4-9b-chat
      --tensor-parallel-size 1
      --max-model-len 32768
      --trust-remote-code
    ports:
      - "8001:8000"
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
              count: 1
    volumes:
      - huggingface-cache:/root/.cache/huggingface
    environment:
      - HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
    restart: unless-stopped

  vllm-minimax:
    image: vllm/vllm-openai:latest
    command: >
      --model MiniMaxAI/MiniMax-M1-80k
      --tensor-parallel-size 2
      --max-model-len 65536
      --trust-remote-code
    ports:
      - "8002:8000"
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
              count: 2
    volumes:
      - huggingface-cache:/root/.cache/huggingface
    environment:
      - HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
    restart: unless-stopped

volumes:
  huggingface-cache:
```

**File: `examples/agents/open_model_gateway/vllm/vllm_models.yaml`**

Reference table of models, HuggingFace IDs, GPU requirements, and recommended vLLM args.

### How to run

```bash
cd examples/agents/open_model_gateway/vllm
HF_TOKEN=hf_xxx docker compose up -d

# Verify
curl http://localhost:8001/v1/models  # should list glm-4-9b-chat
curl http://localhost:8002/v1/models  # should list MiniMax-M1-80k
```

### Depends on

Nothing — can be done independently.

---

## Phase 2: Enhance ROCK Gateway Trace Recording

> The core code changes. Everything below is in existing ROCK source files.

### Step 2a: Update config — add trace settings

**CHANGE file: `rock/sdk/model/server/config.py`**

Add to `ModelServiceConfig`:

```python
trace_db_enabled: bool = Field(default=True)
"""Enable SQLite trace database for queryable trace storage."""

trace_db_path: str = Field(default="./data/traces.db")
"""Path to SQLite trace database file."""

trace_file_path: str = Field(default="./data/LLMTraj.jsonl")
"""Path to JSONL trace file. Replaces the module-level TRAJ_FILE constant."""
```

Remove module-level `TRAJ_FILE` constant (move it into config).

### Step 2b: Enhance `@record_traj` with metadata

**CHANGE file: `rock/sdk/model/server/utils.py`**

Current state — only saves `{"request": body, "response": response_data}`.

New state — the decorator must accept the FastAPI `Request` object and capture:

```python
{
    "trace_id": "<uuid4>",
    "timestamp": "2026-03-07T14:23:01.123Z",
    "user_id": request.headers.get("X-Rock-User-Id", "anonymous"),
    "session_id": request.headers.get("X-Rock-Session-Id", ""),
    "agent_type": request.headers.get("X-Rock-Agent-Type", ""),
    "model": body.get("model", ""),
    "latency_ms": <end_time - start_time in ms>,
    "status": "success" | "error",
    "error": "<error message if failed, else null>",
    "token_usage": {  # extracted from response
        "prompt_tokens": ...,
        "completion_tokens": ...,
        "total_tokens": ...
    },
    "request": body,
    "response": response_data
}
```

Key changes:
- Decorator wraps with `time.time()` before/after to measure latency
- Reads `X-Rock-*` headers from the `Request` object
- Extracts `usage` from response JSON
- Generates a `trace_id` (uuid4) per call
- Writes to JSONL (as before) AND optionally to SQLite (new)

### Step 2c: Update proxy endpoint to pass Request to decorator

**CHANGE file: `rock/sdk/model/server/api/proxy.py`**

The `@record_traj` decorator already wraps `chat_completions(body, request)`. The change is that `record_traj` now needs to read `request` from the function kwargs. The function signature already has `request: Request` — just need the decorator to extract it.

Also handle error cases: when the proxy catches `HTTPStatusError` or other exceptions, still record a trace with `status: "error"`.

### Depends on

- Phase 1 must be running (vLLM) to actually test end-to-end, but code changes can be written independently.

---

## Phase 3: SQLite Trace Store

### Step 3a: Create trace store module

**CREATE file: `rock/sdk/model/server/trace_store.py`**

Simple SQLite-backed store. One table:

```sql
CREATE TABLE IF NOT EXISTS traces (
    trace_id     TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    session_id   TEXT DEFAULT '',
    agent_type   TEXT DEFAULT '',
    model        TEXT NOT NULL,
    latency_ms   REAL,
    status       TEXT NOT NULL,  -- 'success' or 'error'
    error        TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    request_body TEXT,  -- JSON string
    response_body TEXT  -- JSON string
);

CREATE INDEX IF NOT EXISTS idx_traces_user_id ON traces(user_id);
CREATE INDEX IF NOT EXISTS idx_traces_model ON traces(model);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);
```

Python class:

```python
class TraceStore:
    def __init__(self, db_path: str): ...
    def insert(self, trace: dict): ...
    def query(self, user_id=None, model=None, status=None, start=None, end=None, limit=100, offset=0) -> list[dict]: ...
    def get(self, trace_id: str) -> dict | None: ...
    def stats(self, user_id=None, model=None) -> dict: ...
        # returns: total_calls, error_rate, avg_latency_ms, per_model breakdown
```

### Step 3b: Wire trace store into `utils.py`

**CHANGE file: `rock/sdk/model/server/utils.py`**

In `_write_traj`, after writing JSONL, also call `trace_store.insert(data)` if `trace_db_enabled`.

The `TraceStore` singleton is initialized in `main.py` during app startup and stored in `app.state`.

### Step 3c: Initialize trace store in app startup

**CHANGE file: `rock/sdk/model/server/main.py`**

In the `lifespan` function, after setting `app.state.model_service_config`, add:

```python
if config.trace_db_enabled:
    from rock.sdk.model.server.trace_store import TraceStore
    app.state.trace_store = TraceStore(config.trace_db_path)
```

### Depends on

Phase 2 (trace data format must be defined first).

---

## Phase 4: Trace Query API

### Step 4a: Create trace API router

**CREATE file: `rock/sdk/model/server/api/traces.py`**

Three endpoints:

```
GET /v1/traces?user_id=&model=&status=&start=&end=&limit=50&offset=0
    → Returns list of trace summaries (without full request/response bodies)

GET /v1/traces/{trace_id}
    → Returns full trace detail including request/response bodies

GET /v1/traces/stats?user_id=&model=
    → Returns aggregate stats:
      {
        "total_calls": 1234,
        "error_count": 56,
        "error_rate": 0.045,
        "avg_latency_ms": 2340,
        "by_model": {"glm-5": {"calls": 800, "errors": 30}, ...},
        "by_user": {"alice": {"calls": 200, "errors": 5}, ...}
      }
```

### Step 4b: Register router in app

**CHANGE file: `rock/sdk/model/server/main.py`**

Add `traces_router` to the app (always, even if `trace_db_enabled=False` — return 404 in that case).

```python
from rock.sdk.model.server.api.traces import traces_router
app.include_router(traces_router, prefix="", tags=["traces"])
```

### Depends on

Phase 3 (needs TraceStore).

---

## Phase 5: Example Setup + Engineer Onboarding

### What to create

**File: `examples/agents/open_model_gateway/gateway_config.yaml`**

```yaml
host: "0.0.0.0"
port: 8080
proxy_rules:
  "glm-5":   "http://localhost:8001/v1"
  "minimax":  "http://localhost:8002/v1"
  "default":  "http://localhost:8001/v1"
trace_db_enabled: true
trace_db_path: "./data/traces.db"
trace_file_path: "./data/LLMTraj.jsonl"
retryable_status_codes: [429, 500, 502, 503]
request_timeout: 120
```

**File: `examples/agents/open_model_gateway/engineer_setup.sh`**

```bash
#!/bin/bash
# One-time setup for engineers to use the coding agent with open models

GATEWAY_URL="${1:-http://gateway.internal:8080/v1}"
USER_ID="${2:-$(whoami)}"

echo "Installing iflow CLI..."
npm install -g @anthropic-ai/iflow-cli

echo "Configuring environment..."
cat >> ~/.bashrc << EOF

# ROCK Coding Agent Gateway
export IFLOW_BASE_URL="${GATEWAY_URL}"
export IFLOW_MODEL_NAME="glm-5"
export IFLOW_API_KEY="${USER_ID}"
EOF

source ~/.bashrc
echo "Done. Run: iflow \"your prompt here\""
```

**File: `examples/agents/open_model_gateway/README.md`**

Instructions covering:
1. Server setup (vLLM + gateway)
2. Engineer onboarding (run engineer_setup.sh)
3. How to view traces

### Depends on

All previous phases.

---

## Phase 6: Tests

**CREATE file: `tests/unit/sdk/model/test_trace_store.py`**

- Test `TraceStore.insert()` and `TraceStore.query()` with filters
- Test `TraceStore.get()` by trace_id
- Test `TraceStore.stats()` aggregation
- Use in-memory SQLite (`:memory:`)

**CREATE file: `tests/unit/sdk/model/test_enhanced_traj.py`**

- Test enhanced `@record_traj` captures all metadata fields
- Test it handles missing headers gracefully (defaults to "anonymous")
- Test error cases produce `status: "error"` traces
- Test latency measurement is reasonable

**CREATE file: `tests/unit/sdk/model/test_traces_api.py`**

- Test `GET /v1/traces` with various filters
- Test `GET /v1/traces/{trace_id}` returns full detail
- Test `GET /v1/traces/stats` returns correct aggregates
- Use FastAPI TestClient

### Depends on

Write tests alongside each phase (TDD).

---

## Summary: Files Changed vs Created

### CHANGED (existing files)

| File | What changes |
|------|-------------|
| `rock/sdk/model/server/config.py` | Add `trace_db_enabled`, `trace_db_path`, `trace_file_path` fields |
| `rock/sdk/model/server/utils.py` | Enhance `@record_traj` with metadata, latency, headers, SQLite write |
| `rock/sdk/model/server/api/proxy.py` | Record traces on error paths too, pass request context |
| `rock/sdk/model/server/main.py` | Init TraceStore on startup, register traces router |

### CREATED (new files)

| File | Purpose |
|------|---------|
| `rock/sdk/model/server/trace_store.py` | SQLite trace storage + query |
| `rock/sdk/model/server/api/traces.py` | REST API for trace queries |
| `examples/agents/open_model_gateway/vllm/docker-compose.yaml` | vLLM deployment |
| `examples/agents/open_model_gateway/vllm/vllm_models.yaml` | Model reference table |
| `examples/agents/open_model_gateway/gateway_config.yaml` | Gateway config example |
| `examples/agents/open_model_gateway/engineer_setup.sh` | Engineer onboarding script |
| `examples/agents/open_model_gateway/README.md` | Full setup instructions |
| `tests/unit/sdk/model/test_trace_store.py` | TraceStore unit tests |
| `tests/unit/sdk/model/test_enhanced_traj.py` | Enhanced traj decorator tests |
| `tests/unit/sdk/model/test_traces_api.py` | Traces API endpoint tests |

### DOWNLOADED (external dependencies)

| Item | Where | How |
|------|-------|-----|
| vLLM Docker image | GPU server | `docker pull vllm/vllm-openai:latest` |
| NVIDIA Container Toolkit | GPU server | System package install |
| Model weights (GLM-5, MiniMax) | GPU server (auto-cached) | Auto-downloaded by vLLM from HuggingFace |
| iflow CLI | Each engineer's laptop | `npm install -g @anthropic-ai/iflow-cli` |

### NO new Python dependencies

Everything uses stdlib (`sqlite3`, `uuid`, `time`, `json`) + already-installed packages (`FastAPI`, `pydantic`, `httpx`).

---

## Implementation Order (what to do first → last)

```
Phase 1  →  Phase 2a → 2b → 2c  →  Phase 3a → 3b → 3c  →  Phase 4a → 4b  →  Phase 5
(vLLM)      (config)  (traj)  (proxy)  (store)  (wire)  (init)  (API)    (register) (example)
 deploy      │←── can be done in parallel ──→│   │←── depends on 2 ──→│  │←─ dep 3 ─→│
```

Tests are written alongside each phase.
