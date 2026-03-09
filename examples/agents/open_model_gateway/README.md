# ROCK Model Gateway — Open Model Setup

Run a self-hosted LLM (Qwen3.5-35B-A3B via vLLM) behind the ROCK gateway with full trace collection.

## Prerequisites

- ROCK installed (`cd ROCK && make init`)
- vLLM running on port 8000 (see main CLAUDE.md for docker command)
- GPU server with 4x GPUs

## Start the Gateway

```bash
cd ROCK
python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file examples/agents/open_model_gateway/gateway_config.yaml \
  --host 0.0.0.0 --port 8080
```

Verify:
```bash
curl http://localhost:8080/health
```

## Engineer Onboarding

```bash
./examples/agents/open_model_gateway/engineer_setup.sh http://<gateway-host>:8080 <your-name>
```

Or manually set environment variables:
```bash
export IFLOW_BASE_URL="http://<gateway-host>:8080/v1"
export IFLOW_MODEL_NAME="Qwen/Qwen3.5-35B-A3B"
export IFLOW_API_KEY="<your-name>"   # used as user_id for tracing
```

## Trace Inspection

### API
```bash
# List recent traces
curl http://localhost:8080/v1/traces

# Filter by user
curl "http://localhost:8080/v1/traces?user_id=alice"

# Get a specific trace
curl http://localhost:8080/v1/traces/<trace-id>

# Aggregate stats
curl http://localhost:8080/v1/traces/stats
```

### SQLite
```bash
sqlite3 /data/logs/traces.db "SELECT trace_id, user_id, model, status, latency_ms FROM traces ORDER BY timestamp DESC LIMIT 10"
```

### JSONL
```bash
tail -5 /data/logs/LLMTraj.jsonl | python -m json.tool
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Gateway returns 502 | Check vLLM is running: `curl http://localhost:8000/health` |
| Out of GPU memory | Reduce `--max-model-len` or `--max-num-batched-tokens` in vLLM |
| Traces not appearing | Check `trace_db_enabled: true` in config |
| Slow responses | Single sequence mode (`--max-num-seqs 1`) — expected for large models |
