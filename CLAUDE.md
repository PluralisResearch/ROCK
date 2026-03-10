# CLAUDE.md

## What This Project Is

A central model gateway that lets our engineering team use the **iflow** coding agent CLI backed by a self-hosted **Qwen/Qwen3.5-9B** model via vLLM. All LLM calls pass through the ROCK gateway, which records traces (who called what, when, latency, tokens, success/fail) for later analysis and improvement.

```
Engineer laptop (iflow CLI)
    → ROCK Model Gateway (:8080, trace logging)
        → Hosted vLLM endpoint (:8000, Qwen3.5-9B)
```

## Current Status

All phases complete. Both services running as background processes (`nohup`).

- **vLLM**: Running (docker, port 8000) — `Qwen/Qwen3.5-9B`, 256K context window
- **ROCK Gateway**: Running (port 8080) — proxy + SQLite trace logging + trace query API + dashboard

**For full setup and operational details, see [`how_to_run.md`](../how_to_run.md).**

## Repository Layout

| Directory | Purpose |
|-----------|---------|
| `ROCK/` | ROCK framework — gateway server, SDK, admin, sandbox management |
| `ROCK/rock/sdk/model/server/` | **Model gateway server** — proxy, config, tracing, API |
| `iflow-cli/` | iflow coding agent CLI (used by engineers on their laptops) |

## Key Files

### Gateway Server
- `ROCK/rock/sdk/model/server/config.py` — `ModelServiceConfig` (host, port, proxy_base_url, retryable_status_codes, request_timeout, trace_db_enabled, session_timeout_minutes)
- `ROCK/rock/sdk/model/server/utils.py` — `@record_traj` decorator — writes enhanced traces to JSONL, integrates session inference
- `ROCK/rock/sdk/model/server/api/proxy.py` — `/v1/chat/completions` proxy with retry logic (non-streaming only)
- `ROCK/rock/sdk/model/server/main.py` — FastAPI app, `/health` endpoint, CLI arg parsing
- `ROCK/rock/sdk/model/server/session.py` — `SessionManager` — server-side session inference from message fingerprints
- `ROCK/rock/sdk/model/server/trace_store.py` — SQLite trace storage with per-user, per-session, and timeline queries
- `ROCK/rock/sdk/model/server/api/traces.py` — `GET /v1/traces`, `/v1/traces/{id}`, `/v1/traces/stats`, `/v1/traces/users`, `/v1/traces/sessions`, `/v1/traces/timeline`, `/v1/traces/conversation`
- `ROCK/rock/sdk/model/server/dashboard.py` — `GET /dashboard` — HTML trace visualization dashboard with conversation viewer (Chart.js, Melbourne timezone)
- `ROCK/rock/sdk/model/server/migrate_sessions.py` — Backfill script for existing traces without session IDs
- `ROCK/examples/agents/open_model_gateway/gateway_config.yaml` — Gateway config

### Documentation
- `how_to_run.md` — **Full setup guide** for server admins and engineers (start here)
- `ROCK/plan.md` — Original implementation plan (phases 1–6, all complete)

## Commands

```bash
# Install ROCK dependencies
cd ROCK && make init
uv sync --all-extras --all-groups

# Run tests (fast, no external deps)
cd ROCK && uv run pytest -m "not need_ray and not need_admin and not need_admin_and_network" --reruns 1

# Lint & format
cd ROCK && uv run ruff check --fix . && uv run ruff format .

# Start gateway (background)
cd ROCK
export ROCK_MODEL_SERVICE_DATA_DIR="$HOME/pluralis-local-agent/ROCK/data"
nohup .venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file examples/agents/open_model_gateway/gateway_config.yaml \
  --host 0.0.0.0 --port 8080 > gateway.log 2>&1 &

# Health check
curl http://localhost:8080/health
```

## The Model

**Qwen/Qwen3.5-9B** served via vLLM with tool-calling support. Context window: **262144 tokens**.

```bash
nohup docker run --runtime nvidia --gpus all \
  -p 8000:8000 --ipc=host \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN=$HF_TOKEN \
  vllm/vllm-openai:latest \
  Qwen/Qwen3.5-9B \
  --tensor-parallel-size 4 \
  --max-model-len 262144 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 2048 \
  --gpu-memory-utilization 0.95 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder > vllm.log 2>&1 &
```

## Session Inference

Sessions are inferred server-side automatically — no client changes needed. The algorithm fingerprints the first user message in each conversation (SHA-256, first 16 hex chars). Same user + same fingerprint + within timeout (default 30min) = same session. Configure via `session_timeout_minutes` in `gateway_config.yaml`.

If a client sends `X-Rock-Session-Id` header, that takes precedence over inference.

## Dashboard

Accessible at `http://<server-ip>:8080/dashboard` (same port as gateway, no extra setup). All times displayed in **Melbourne timezone** (AEDT/AEST). Shows:
- Summary cards (requests, success rate, latency, tokens, users)
- Timeline charts (requests, latency, token usage over time)
- Users table (click a user to view their conversations)
- Sessions table (click a session to view the full conversation thread)
- Recent errors table
- **Conversation viewer** — modal showing full message history (system/user/assistant), with compact mode to show only the latest turn per request

## Trace Collection

The `@record_traj` decorator writes enhanced traces (user_id, session_id, latency, token usage, status) to both `LLMTraj.jsonl` and a SQLite database (`traces.db`). Query via the trace API:

```bash
curl "http://localhost:8080/v1/traces?user_id=alice&limit=10"
curl "http://localhost:8080/v1/traces/stats"
curl "http://localhost:8080/v1/traces/users"
curl "http://localhost:8080/v1/traces/sessions?user_id=alice"
curl "http://localhost:8080/v1/traces/timeline?interval=hour"
curl "http://localhost:8080/v1/traces/conversation?user_id=alice&limit=10"
```

## Code Conventions

- Follow ROCK's existing patterns (see `ROCK/CLAUDE.md` for full details)
- Logger: `from rock.logger import init_logger; logger = init_logger(__name__)`
- Pydantic v2 for API models, FastAPI async handlers
- No new Python dependencies — use stdlib (`sqlite3`, `uuid`, `time`, `json`) + existing FastAPI/pydantic/httpx
- Lint: `ruff` (line length 120)
- Tests: pytest with `asyncio_mode = "auto"`, strict markers

## Engineer Onboarding (iflow)

See [`how_to_run.md`](../how_to_run.md) Part B for the full engineer setup guide. Quick config:

```json
{
  "selectedAuthType": "custom",
  "apiKey": "<your-name>",
  "baseUrl": "http://localhost:8080/v1",
  "modelName": "Qwen/Qwen3.5-9B"
}
```

Save to `~/.iflow/settings.json`, then run `iflow`.
