# Runbook: Open Model Coding Agent Gateway

## Prerequisites

| Machine | Requirements |
|---------|-------------|
| **GPU Server** | Linux, Docker, NVIDIA GPU(s), NVIDIA Container Toolkit installed |
| **Your MacBook** | Node.js (for iflow CLI), network access to GPU server |

---

## Part 1: GPU Server Setup

### 1.1 Install NVIDIA Container Toolkit (if not already)

```bash
# Add NVIDIA repo
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU is visible to Docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### 1.2 Start vLLM Model Servers

```bash
# Clone ROCK repo (or navigate to it)
cd /path/to/ROCK/examples/agents/open_model_gateway/vllm

# Set your HuggingFace token (needed for gated models)
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxx

# Start model servers
docker compose up -d

# Watch startup logs (first run downloads model weights — can take 10-30 min)
docker compose logs -f vllm-glm5
docker compose logs -f vllm-minimax
```

**Wait until you see** `Uvicorn running on http://0.0.0.0:8000` in both logs.

```bash
# Verify models are loaded
curl http://localhost:8001/v1/models
# Expected: {"data": [{"id": "THUDM/glm-4-9b-chat", ...}]}

curl http://localhost:8002/v1/models
# Expected: {"data": [{"id": "MiniMaxAI/MiniMax-M1-80k", ...}]}

# Quick smoke test — send a chat completion directly to vLLM
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "THUDM/glm-4-9b-chat",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 50
  }'
```

### 1.3 Start the ROCK Model Gateway

```bash
cd /path/to/ROCK/examples/agents/open_model_gateway

# Start gateway (routes requests to vLLM, logs all traces)
rock model-service start --type proxy --config-file gateway_config.yaml

# Or run directly with Python if `rock` CLI isn't installed:
python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file gateway_config.yaml \
  --host 0.0.0.0 \
  --port 8080
```

```bash
# Verify gateway is healthy
curl http://localhost:8080/health
# Expected: {"status": "healthy"}

# Test end-to-end: gateway → vLLM → response
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Rock-User-Id: test-user" \
  -d '{
    "model": "glm-5",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

### 1.4 Make Gateway Accessible to Engineers

Ensure port `8080` is reachable from engineer laptops. Options:

| Method | Command / Config |
|--------|-----------------|
| Direct (same network) | Engineers use `http://<gpu-server-ip>:8080/v1` |
| SSH tunnel | `ssh -L 8080:localhost:8080 user@gpu-server` |
| Reverse proxy (nginx) | Proxy `gateway.internal:443` → `localhost:8080` |
| Tailscale / WireGuard | VPN mesh — engineers access `http://gpu-server:8080/v1` |

Pick one. For a team of <20, direct IP or Tailscale is simplest.

---

## Part 2: MacBook Setup (Each Engineer)

### 2.1 One-Time Setup

```bash
# Install the coding agent CLI
npm install -g @anthropic-ai/iflow-cli

# Configure environment — add to ~/.zshrc (or ~/.bashrc)
echo '' >> ~/.zshrc
echo '# Coding Agent - Open Model Gateway' >> ~/.zshrc
echo 'export IFLOW_BASE_URL="http://<gpu-server-ip>:8080/v1"' >> ~/.zshrc
echo 'export IFLOW_MODEL_NAME="glm-5"' >> ~/.zshrc
echo 'export IFLOW_API_KEY="your-name"' >> ~/.zshrc
source ~/.zshrc
```

Replace:
- `<gpu-server-ip>` with the actual IP/hostname of your GPU server
- `your-name` with the engineer's name or ID (used for trace identification)

### 2.2 Verify Setup

```bash
# Check CLI is installed
iflow --version

# Quick test
iflow "print hello world in python"
```

If you see a response, everything is working. The gateway is routing your request to GLM-5 via vLLM, and the trace is being recorded.

### 2.3 Daily Usage

```bash
# Navigate to any project
cd ~/projects/my-app

# Use the agent on your real code
iflow "fix the null pointer exception in auth.py"
iflow "add unit tests for the UserService class"
iflow "refactor the database connection pool to use async"
```

That's it. The agent works on your local files. Every LLM call goes through the gateway and gets logged.

### 2.4 Switch Models

```bash
# Use MiniMax instead of GLM-5 (temporary, for one session)
IFLOW_MODEL_NAME="minimax" iflow "explain this function"

# Or change default permanently
sed -i '' 's/IFLOW_MODEL_NAME="glm-5"/IFLOW_MODEL_NAME="minimax"/' ~/.zshrc
source ~/.zshrc
```

---

## Part 3: Checking Traces

### 3.1 Quick Check — JSONL File (on GPU server)

```bash
# See the last 10 traces
tail -20 /path/to/ROCK/examples/agents/open_model_gateway/data/LLMTraj.jsonl | python -m json.tool

# Count total traces
wc -l data/LLMTraj.jsonl

# See traces from a specific user
grep '"user_id": "alice"' data/LLMTraj.jsonl | python -m json.tool

# See all errors
grep '"status": "error"' data/LLMTraj.jsonl | python -m json.tool

# Count calls per user
cat data/LLMTraj.jsonl | python3 -c "
import json, sys, collections
users = collections.Counter()
for line in sys.stdin:
    d = json.loads(line)
    users[d.get('user_id', 'unknown')] += 1
for u, c in users.most_common():
    print(f'{u}: {c} calls')
"
```

### 3.2 Trace Query API (after Phase 4 is implemented)

```bash
# All traces, latest first
curl "http://<gpu-server-ip>:8080/v1/traces?limit=20"

# Filter by user
curl "http://<gpu-server-ip>:8080/v1/traces?user_id=alice&limit=10"

# Filter by model and status
curl "http://<gpu-server-ip>:8080/v1/traces?model=glm-5&status=error"

# Filter by date range
curl "http://<gpu-server-ip>:8080/v1/traces?start=2026-03-01&end=2026-03-07"

# Get full detail of a specific trace (includes request/response bodies)
curl "http://<gpu-server-ip>:8080/v1/traces/abc-123-trace-id"

# Aggregate stats
curl "http://<gpu-server-ip>:8080/v1/traces/stats"
# Returns:
# {
#   "total_calls": 1234,
#   "error_count": 56,
#   "error_rate": 0.045,
#   "avg_latency_ms": 2340,
#   "by_model": {
#     "glm-5": {"calls": 800, "errors": 30, "avg_latency_ms": 2100},
#     "minimax": {"calls": 434, "errors": 26, "avg_latency_ms": 2780}
#   },
#   "by_user": {
#     "alice": {"calls": 200, "errors": 5},
#     "bob": {"calls": 150, "errors": 12}
#   }
# }

# Stats for a specific user
curl "http://<gpu-server-ip>:8080/v1/traces/stats?user_id=alice"
```

### 3.3 SQLite Direct Query (on GPU server, after Phase 3 is implemented)

```bash
# Open the trace database
sqlite3 data/traces.db

# Top users by call count
SELECT user_id, COUNT(*) as calls,
       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
       ROUND(AVG(latency_ms)) as avg_latency
FROM traces
GROUP BY user_id
ORDER BY calls DESC;

# Most common errors
SELECT error, COUNT(*) as count
FROM traces
WHERE status='error'
GROUP BY error
ORDER BY count DESC
LIMIT 10;

# Traces from today
SELECT trace_id, user_id, model, status, latency_ms
FROM traces
WHERE timestamp >= date('now')
ORDER BY timestamp DESC;

# Daily usage trend
SELECT date(timestamp) as day, COUNT(*) as calls,
       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors
FROM traces
GROUP BY day
ORDER BY day DESC
LIMIT 14;

# Total tokens consumed per user
SELECT user_id,
       SUM(prompt_tokens) as total_prompt,
       SUM(completion_tokens) as total_completion,
       SUM(total_tokens) as total
FROM traces
GROUP BY user_id
ORDER BY total DESC;
```

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| `curl: (7) Failed to connect` to gateway | Is the gateway running? `ps aux \| grep model.server` |
| `curl: (7) Failed to connect` to vLLM | `docker compose ps` — is the container healthy? |
| vLLM OOM on startup | Reduce `--max-model-len` or use a smaller model |
| Engineer gets `Model 'glm-5' is not configured` | Check `gateway_config.yaml` — the model name must match what the engineer sends in `IFLOW_MODEL_NAME` |
| Traces not appearing | Check `data/` directory exists and is writable. Check gateway logs for errors |
| Slow responses (>30s) | Check GPU utilization with `nvidia-smi`. vLLM may be overloaded — add `--max-num-seqs 8` to limit concurrency |
| Agent CLI hangs | The gateway currently rejects `stream=True`. Ensure agent is configured for non-streaming mode |

---

## Service Management

```bash
# === vLLM ===
docker compose up -d          # Start
docker compose down            # Stop
docker compose restart vllm-glm5  # Restart one model
docker compose logs -f         # Watch logs

# === Gateway ===
# Start in background
nohup python -m rock.sdk.model.server.main \
  --type proxy --config-file gateway_config.yaml \
  --host 0.0.0.0 --port 8080 > gateway.log 2>&1 &

# Stop
kill $(pgrep -f "rock.sdk.model.server.main")

# Check status
curl http://localhost:8080/health
```
