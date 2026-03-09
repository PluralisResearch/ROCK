# Plan: Central Model Gateway for Coding Agents (Single Hosted Model)

## Goal

Engineers use a coding agent CLI (iflow/similar) locally on their real repos.
A single hosted model is used via vLLM:
`Qwen/Qwen3.5-35B-A3B`.
All LLM calls are traced centrally with metadata (who, when, model, success/fail).
ROCK gateway is started/stopped with `~/pluralis-local-agent/ROCK/.venv/bin/python`.

## Architecture

```
Engineer's laptop                    Gateway Host
┌────────────────┐                  ┌──────────────────────────────────┐
│ iflow CLI      │                  │ ROCK Model Gateway (:8080)       │
│ (works on real │── /v1/chat/──>   │ (trace logging + routing)        │
│ local files)   │   completions    │        │                         │
└────────────────┘                  │        ▼                         │
                                    │  Hosted vLLM endpoint            │
                                    │  Qwen/Qwen3.5-35B-A3B            │
                                    └──────────────────────────────────┘
```

---

## Phase 1: Use Existing Hosted vLLM Endpoint

> No GPU/toolkit deployment work in this plan. Model hosting already exists.

Validate current model server:

```bash
curl http://localhost:8000/v1/models
# Should include Qwen/Qwen3.5-35B-A3B
```

Gateway config should route only this model.
ROCK gateway should be started/stopped via the ROCK venv Python.

```bash
cd ~/pluralis-local-agent/ROCK/examples/agents/open_model_gateway

# Start
~/pluralis-local-agent/ROCK/.venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file gateway_config.yaml \
  --host 0.0.0.0 \
  --port 8080

# Stop
pkill -f "rock.sdk.model.server.main"
```

---

## Phase 2: Enhance ROCK Gateway Trace Recording

### Step 2a: Update config — add trace settings

**CHANGE file: `rock/sdk/model/server/config.py`**

Add to `ModelServiceConfig`:

```python
trace_db_enabled: bool = Field(default=True)
trace_db_path: str = Field(default="./data/traces.db")
trace_file_path: str = Field(default="./data/LLMTraj.jsonl")
```

### Step 2b: Enhance `@record_traj` with metadata

**CHANGE file: `rock/sdk/model/server/utils.py`**

Capture request/response plus metadata:

```python
{
    "trace_id": "<uuid4>",
    "timestamp": "2026-03-07T14:23:01.123Z",
    "user_id": request.headers.get("X-Rock-User-Id", "anonymous"),
    "session_id": request.headers.get("X-Rock-Session-Id", ""),
    "agent_type": request.headers.get("X-Rock-Agent-Type", ""),
    "model": body.get("model", "Qwen/Qwen3.5-35B-A3B"),
    "latency_ms": <end_time - start_time in ms>,
    "status": "success" | "error",
    "error": "<error message if failed, else null>",
    "token_usage": {
        "prompt_tokens": ...,
        "completion_tokens": ...,
        "total_tokens": ...
    },
    "request": body,
    "response": response_data
}
```

### Step 2c: Update proxy endpoint for error-path trace recording

**CHANGE file: `rock/sdk/model/server/api/proxy.py`**

Ensure traces are written for both success and error paths.

---

## Phase 3: SQLite Trace Store

### Step 3a: Create trace store module

**CREATE file: `rock/sdk/model/server/trace_store.py`**

```sql
CREATE TABLE IF NOT EXISTS traces (
    trace_id     TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    session_id   TEXT DEFAULT '',
    agent_type   TEXT DEFAULT '',
    model        TEXT NOT NULL,
    latency_ms   REAL,
    status       TEXT NOT NULL,
    error        TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    request_body TEXT,
    response_body TEXT
);
```

Create indexes for `user_id`, `model`, `timestamp`, `status`.

### Step 3b: Wire trace store into `utils.py`

**CHANGE file: `rock/sdk/model/server/utils.py`**

After JSONL write, call `trace_store.insert(data)` when enabled.

### Step 3c: Initialize trace store in app startup

**CHANGE file: `rock/sdk/model/server/main.py`**

Initialize `TraceStore` in app lifespan and attach to `app.state`.

---

## Phase 4: Trace Query API

### Step 4a: Create trace API router

**CREATE file: `rock/sdk/model/server/api/traces.py`**

Endpoints:

- `GET /v1/traces?user_id=&model=&status=&start=&end=&limit=50&offset=0`
- `GET /v1/traces/{trace_id}`
- `GET /v1/traces/stats?user_id=&model=`

### Step 4b: Register router in app

**CHANGE file: `rock/sdk/model/server/main.py`**

Include traces router in FastAPI app setup.

---

## Phase 5: Example Setup + Engineer Onboarding

### What to create

**File: `examples/agents/open_model_gateway/gateway_config.yaml`**

```yaml
host: "0.0.0.0"
port: 8080
proxy_rules:
  "Qwen/Qwen3.5-35B-A3B": "http://localhost:8000/v1"
  "default": "http://localhost:8000/v1"
trace_db_enabled: true
trace_db_path: "./data/traces.db"
trace_file_path: "./data/LLMTraj.jsonl"
retryable_status_codes: [429, 500, 502, 503]
request_timeout: 120
```

**File: `examples/agents/open_model_gateway/engineer_setup.sh`**

```bash
#!/bin/bash
GATEWAY_URL="${1:-http://gateway.internal:8080/v1}"
USER_ID="${2:-$(whoami)}"

npm install -g @anthropic-ai/iflow-cli

cat >> ~/.bashrc << EOF2

# ROCK Coding Agent Gateway
export IFLOW_BASE_URL="${GATEWAY_URL}"
export IFLOW_MODEL_NAME="Qwen/Qwen3.5-35B-A3B"
export IFLOW_API_KEY="${USER_ID}"
EOF2

source ~/.bashrc
```

**File: `examples/agents/open_model_gateway/README.md`**

Instructions covering:
1. Gateway setup
2. Engineer onboarding
3. Trace inspection

---

## Phase 6: Tests

**CREATE file: `tests/unit/sdk/model/test_trace_store.py`**
- Test insert/query/get/stats with in-memory SQLite.

**CREATE file: `tests/unit/sdk/model/test_enhanced_traj.py`**
- Test metadata capture, defaults, and error-path traces.

**CREATE file: `tests/unit/sdk/model/test_traces_api.py`**
- Test traces list/detail/stats endpoints with filters.

---

## Summary: Files Changed vs Created

### CHANGED (existing files)

| File | What changes |
|------|-------------|
| `rock/sdk/model/server/config.py` | Add `trace_db_enabled`, `trace_db_path`, `trace_file_path` |
| `rock/sdk/model/server/utils.py` | Enhance `@record_traj` with metadata and SQLite write |
| `rock/sdk/model/server/api/proxy.py` | Record traces on error paths too |
| `rock/sdk/model/server/main.py` | Init TraceStore and register traces router |

### CREATED (new files)

| File | Purpose |
|------|---------|
| `rock/sdk/model/server/trace_store.py` | SQLite trace storage + query |
| `rock/sdk/model/server/api/traces.py` | Trace query API |
| `examples/agents/open_model_gateway/gateway_config.yaml` | Single-model gateway config |
| `examples/agents/open_model_gateway/engineer_setup.sh` | Engineer onboarding script |
| `examples/agents/open_model_gateway/README.md` | Setup instructions |
| `tests/unit/sdk/model/test_trace_store.py` | TraceStore tests |
| `tests/unit/sdk/model/test_enhanced_traj.py` | Traj decorator tests |
| `tests/unit/sdk/model/test_traces_api.py` | Traces API tests |

### DOWNLOADED (external dependencies)

| Item | Where | How |
|------|-------|-----|
| iflow CLI | Engineer laptop | `npm install -g @anthropic-ai/iflow-cli` |

### NO new Python dependencies

Uses stdlib (`sqlite3`, `uuid`, `time`, `json`) + existing FastAPI/pydantic/httpx.

---

## Implementation Order

```
Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5
(existing   (trace)    (store)    (API)      (onboarding)
hosted
model)
```

Tests should be written alongside each phase.
