# Runbook: Open Model Coding Agent Gateway

## Prerequisites

| Machine | Requirements |
|---------|-------------|
| **Model Server** | vLLM already running on `http://localhost:8000/v1` |
| **Gateway Host** | ROCK installed at `~/pluralis-local-agent/ROCK/.venv/bin/python` |
| **Engineer Laptop** | Node.js (for iflow CLI), network access to gateway |

Quick check that the model server is up:

```bash
curl http://localhost:8000/v1/models
# Expected to include: Qwen/Qwen3.5-35B-A3B
```

## Part 1: Start the ROCK Model Gateway

```bash
cd ~/pluralis-local-agent/ROCK/examples/agents/open_model_gateway

# Start gateway from ROCK virtualenv Python
~/pluralis-local-agent/ROCK/.venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file gateway_config.yaml \
  --host 0.0.0.0 \
  --port 8080
```

```bash
# Stop gateway
pkill -f "rock.sdk.model.server.main"
```

```bash
# Verify gateway health
curl http://localhost:8080/health
# Expected: {"status": "healthy"}

# Test end-to-end: gateway -> localhost vLLM -> response
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Rock-User-Id: test-user" \
  -d '{
    "model": "Qwen/Qwen3.5-35B-A3B",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

### Make Gateway Accessible to Engineers

Ensure port `8080` is reachable from engineer laptops. Options:

| Method | Command / Config |
|--------|-----------------|
| Direct (same network) | Engineers use `http://<gateway-host>:8080/v1` |
| SSH tunnel | `ssh -L 8080:localhost:8080 user@<gateway-host>` |
| Reverse proxy (nginx) | Proxy `gateway.internal:443` -> `localhost:8080` |
| Tailscale / WireGuard | VPN mesh -> `http://<gateway-host>:8080/v1` |

## Part 2: Engineer Laptop Setup

### 2.1 One-Time Setup

```bash
# Install the coding agent CLI
npm install -g @anthropic-ai/iflow-cli

# Configure environment — add to ~/.zshrc (or ~/.bashrc)
echo '' >> ~/.zshrc
echo '# Coding Agent - Open Model Gateway' >> ~/.zshrc
echo 'export IFLOW_BASE_URL="http://<gateway-host>:8080/v1"' >> ~/.zshrc
echo 'export IFLOW_MODEL_NAME="Qwen/Qwen3.5-35B-A3B"' >> ~/.zshrc
echo 'export IFLOW_API_KEY="your-name"' >> ~/.zshrc
source ~/.zshrc
```

Replace:
- `<gateway-host>` with your gateway host/IP
- `your-name` with engineer name/ID (for trace attribution)

### 2.2 Verify Setup

```bash
iflow --version
iflow "print hello world in python"
```

If this responds, requests are flowing through the gateway to `Qwen/Qwen3.5-35B-A3B` and traces are recorded.

### 2.3 Daily Usage

```bash
cd ~/projects/my-app
iflow "fix the null pointer exception in auth.py"
iflow "add unit tests for the UserService class"
iflow "refactor the database connection pool to use async"
```

## Part 3: Checking Traces

### 3.1 Quick Check — JSONL File

```bash
# Last traces
tail -20 /path/to/ROCK/examples/agents/open_model_gateway/data/LLMTraj.jsonl | python -m json.tool

# Total traces
wc -l /path/to/ROCK/examples/agents/open_model_gateway/data/LLMTraj.jsonl

# Traces from one user
grep '"user_id": "alice"' /path/to/ROCK/examples/agents/open_model_gateway/data/LLMTraj.jsonl | python -m json.tool

# Error traces
grep '"status": "error"' /path/to/ROCK/examples/agents/open_model_gateway/data/LLMTraj.jsonl | python -m json.tool
```

### 3.2 Trace Query API

```bash
# All traces
curl "http://<gateway-host>:8080/v1/traces?limit=20"

# Filter by user
curl "http://<gateway-host>:8080/v1/traces?user_id=alice&limit=10"

# Filter by model and status
curl "http://<gateway-host>:8080/v1/traces?model=Qwen/Qwen3.5-35B-A3B&status=error"

# Date range
curl "http://<gateway-host>:8080/v1/traces?start=2026-03-01&end=2026-03-07"

# Full detail for one trace
curl "http://<gateway-host>:8080/v1/traces/abc-123-trace-id"

# Aggregate stats
curl "http://<gateway-host>:8080/v1/traces/stats"
```

### 3.3 SQLite Direct Query

```bash
sqlite3 /path/to/ROCK/examples/agents/open_model_gateway/data/traces.db

SELECT user_id, COUNT(*) as calls,
       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
       ROUND(AVG(latency_ms)) as avg_latency
FROM traces
GROUP BY user_id
ORDER BY calls DESC;
```

## Troubleshooting

| Symptom | Check |
|--------|-------|
| `curl: (7) Failed to connect` to gateway | Confirm gateway process is running and port `8080` is open |
| `curl: (7) Failed to connect` to vLLM | Confirm `curl http://localhost:8000/v1/models` works |
| `Model 'Qwen/Qwen3.5-35B-A3B' is not configured` | Check `gateway_config.yaml` model key matches `IFLOW_MODEL_NAME` |
| Slow responses | Check GPU utilization on the host and current request concurrency |
| Empty traces | Verify `trace_file_path` and write permissions |

## Ops Commands

```bash
# Restart gateway from ROCK virtualenv Python
pkill -f "rock.sdk.model.server.main"
nohup ~/pluralis-local-agent/ROCK/.venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file gateway_config.yaml \
  --host 0.0.0.0 \
  --port 8080 > gateway.log 2>&1 &

# Follow gateway logs
tail -f gateway.log
```
