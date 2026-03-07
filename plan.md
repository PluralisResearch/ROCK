# Plan: Central Model Gateway for Coding Agent Evaluation

## Goal
Let engineers use a coding agent (iflow-like) locally on their real repos, powered by open models (GLM-5, MiniMax, etc.), with all LLM traces collected centrally with rich metadata.

## Architecture

```
Engineer's machine              Central Server (GPU)
┌────────────────┐             ┌──────────────────────────────────────┐
│ coding agent   │── API ─────>│ ROCK Model Gateway (:8080)           │
│ (local CLI)    │             │  - OpenAI-compatible                 │
│                │             │  - trace logging (JSONL + SQLite)    │
│ Works on their │             │  - user identification via headers   │
│ real repo      │             │  - routes by model name              │
└────────────────┘             │         │                │           │
                               │    ┌────▼─────┐   ┌─────▼────────┐  │
                               │    │ vLLM #1  │   │ vLLM #2      │  │
                               │    │ GLM-5    │   │ MiniMax      │  │
                               │    │ :8001    │   │ :8002        │  │
                               │    └──────────┘   └──────────────┘  │
                               └──────────────────────────────────────┘
```

## What Already Exists in ROCK
- `rock/sdk/model/server/api/proxy.py` — OpenAI-compatible proxy with `@record_traj`
- `rock/sdk/model/server/utils.py` — JSONL trajectory writer
- `rock/sdk/model/server/config.py` — model routing rules (proxy_rules maps model→backend URL)
- `rock/sdk/model/server/main.py` — FastAPI app with proxy/local modes

## What We Need to Add

### Step 0: vLLM model hosting setup
**Dir: `examples/agents/open_model_gateway/vllm/`**

Provide deployment configs for hosting open models with vLLM. vLLM serves OpenAI-compatible `/v1/chat/completions` natively — the ROCK gateway's `proxy_rules` just points to it.

**Files to create:**
- `docker-compose.yaml` — Docker Compose for running one or more vLLM instances with GPU passthrough
- `vllm_models.yaml` — Reference config listing model names, HuggingFace IDs, GPU requirements, and recommended vLLM args

**Example docker-compose.yaml:**
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

volumes:
  huggingface-cache:
```

**Corresponding gateway config routes to vLLM:**
```yaml
proxy_rules:
  "glm-5":    "http://localhost:8001/v1"
  "minimax":  "http://localhost:8002/v1"
  "default":  "http://localhost:8001/v1"
```

**Why vLLM:**
- Native OpenAI-compatible API — zero adapter code needed
- Continuous batching, PagedAttention — best throughput for concurrent users
- Supports most open models (GLM, Qwen, Llama, MiniMax, etc.)
- `docker-compose up` and it's running — simple ops

### Step 1: Enhance trace recording with metadata
**File: `rock/sdk/model/server/utils.py`**

Current `@record_traj` only saves raw request/response. Enhance to capture:
- `user_id` — from `X-Rock-User-Id` request header
- `session_id` — from `X-Rock-Session-Id` header (to group multi-turn conversations)
- `timestamp` — ISO format
- `latency_ms` — how long the LLM call took
- `model` — which model was used
- `token_usage` — from response (prompt_tokens, completion_tokens, total_tokens)
- `status` — success/error
- `error` — error message if failed
- `agent_type` — from `X-Rock-Agent-Type` header (optional, e.g. "iflow", "swe-agent")

### Step 2: Add SQLite trace store (optional, alongside JSONL)
**New file: `rock/sdk/model/server/trace_store.py`**

Simple SQLite store for queryable traces. One table `traces` with the fields above.
- Enables querying: "show me all failures for user X with model GLM-5"
- JSONL stays as primary append-only log; SQLite is for querying
- Optional — enabled via config flag `trace_db_enabled: true`

### Step 3: Add trace query API endpoints
**New file: `rock/sdk/model/server/api/traces.py`**

Simple read-only API to query collected traces:
- `GET /v1/traces` — list traces with filters (user_id, model, status, date range)
- `GET /v1/traces/{trace_id}` — get single trace detail
- `GET /v1/traces/stats` — aggregate stats (total calls, error rate, avg latency, per-model breakdown)

### Step 4: Update proxy to pass request context to trace recorder
**File: `rock/sdk/model/server/api/proxy.py`**

Update `chat_completions` to extract headers and pass context (user_id, session_id, agent_type) to the trace recorder. Pass the `request` object to `@record_traj` so it can read headers.

### Step 5: Update config for gateway mode
**File: `rock/sdk/model/server/config.py`**

Add fields:
- `trace_db_enabled: bool = True`
- `trace_db_path: str = "./traces.db"`
- `traj_file: str` (move from module-level constant to config)

### Step 6: Create example setup
**Dir: `examples/agents/open_model_gateway/`**

Files:
- `gateway_config.yaml` — sample config routing to GLM-5/MiniMax endpoints
- `README.md` — setup instructions for both gateway operator and engineer users
- `engineer_setup.sh` — one-liner setup script for engineers (install agent CLI, configure endpoint)

### Step 7: Tests
- Unit tests for enhanced trace recording
- Unit tests for trace store (SQLite)
- Unit tests for trace query API

## Engineer Experience (End Result)

**One-time setup (engineer runs):**
```bash
# Install the coding agent
npm install -g @anthropic-ai/iflow-cli

# Configure to use company gateway (one env var)
export IFLOW_BASE_URL="http://gateway.internal:8080/v1"
export IFLOW_MODEL_NAME="glm-5"
export IFLOW_API_KEY="user-alice"  # doubles as user identification
```

**Daily use:**
```bash
cd my-project
iflow "fix the auth bug in login.py"
```

That's it. Agent works on their real files. Every LLM call goes through the gateway and gets logged with their user ID.

**Gateway operator (one-time server setup):**
```bash
# 1. Start vLLM model servers (on GPU machine)
cd examples/agents/open_model_gateway/vllm
HF_TOKEN=your_token docker-compose up -d

# 2. Start the ROCK gateway (routes to vLLM, logs traces)
rock model-service start --type proxy --config-file gateway_config.yaml

# 3. Verify
curl http://localhost:8080/health
curl http://localhost:8001/v1/models   # vLLM GLM-5
curl http://localhost:8002/v1/models   # vLLM MiniMax
```

**Monitor usage:**
```bash
# View traces
curl http://localhost:8080/v1/traces/stats
curl "http://localhost:8080/v1/traces?user_id=alice&status=error"
curl "http://localhost:8080/v1/traces?model=glm-5&limit=20"
```

## Implementation Order

1. **Step 0** (vLLM configs) — deploy configs, can be tested independently
2. **Steps 1 + 4** (trace enhancement + proxy update) — core feature, depend on each other
3. **Step 5** (config update) — small, supports steps 1-4
4. **Step 2** (SQLite store) — builds on step 1
5. **Step 3** (trace query API) — builds on step 2
6. **Step 6** (example + docs) — final integration example
7. **Step 7** (tests) — written alongside each step per TDD
