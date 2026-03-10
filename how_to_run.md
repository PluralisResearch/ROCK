# How to Run: ROCK Model Gateway + iFlow Coding Agent

This guide covers two roles:

- **Backend Engineer (Server Admin)** — Sets up the GPU server: hosts the model, runs the gateway, manages traces, and onboards engineers.
- **Engineer (End User)** — Installs iFlow CLI on their laptop, connects to the gateway, and codes with AI.

```
Engineer's MacBook                      GPU Server (EC2)
┌──────────────────┐                   ┌──────────────────────────────────┐
│  iflow CLI       │                   │                                  │
│  (works on your  │── HTTP ────────>  │  ROCK Gateway (:8080)            │
│   local repo)    │   /v1/chat/       │    ├─ trace logging (JSONL)      │
│                  │   completions     │    ├─ trace storage (SQLite)     │
│                  │                   │    └─ trace query API            │
└──────────────────┘                   │           │                      │
                                       │           ▼                      │
                                       │  vLLM Model Server (:8000)       │
                                       │  Qwen/Qwen3.5-9B                │
                                       │  (Docker, 256K context)           │
                                       └──────────────────────────────────┘
```

---

## Part A: Server Setup (Backend Engineer)

Everything in this section runs on the GPU server.

### Prerequisites

| Requirement | Details |
|-------------|---------|
| OS | Linux (tested on Amazon Linux 2023) |
| GPUs | 4x NVIDIA GPUs (A100/H100/A10G) with nvidia-docker runtime |
| Docker | With `--runtime nvidia` support |
| Python | 3.10–3.12 |
| uv | Rust-based Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/)) |
| HuggingFace token | `$HF_TOKEN` set for model download |
| Disk | ~70GB for model weights in `~/.cache/huggingface` |

### Step 1: Clone the Repository

```bash
cd ~
git clone <repo-url> pluralis-local-agent
cd ~/pluralis-local-agent
```

### Step 2: Install ROCK Dependencies

```bash
cd ~/pluralis-local-agent/ROCK
make init
# or manually:
# uv venv --python 3.11 --python-preference only-managed
# source .venv/bin/activate
# uv sync --all-extras --all-groups
```

Verify:
```bash
~/pluralis-local-agent/ROCK/.venv/bin/python --version
# Python 3.11.x
```

### Step 3: Start the vLLM Model Server

This serves the `Qwen/Qwen3.5-9B` model on port 8000. Run it in the background with `nohup`:

```bash
export HF_TOKEN="<your-huggingface-token>"

nohup docker run --runtime nvidia --gpus all \
  -p 8000:8000 \
  --ipc=host \
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

**Wait for the model to finish loading** (can take 2–5 minutes on first download, ~30s on subsequent starts):

```bash
tail -f ~/vllm.log
# Wait until you see: Uvicorn running on http://0.0.0.0:8000
```

Verify:
```bash
curl http://localhost:8000/v1/models
# Should list Qwen/Qwen3.5-9B
```

#### vLLM Parameter Reference

| Parameter | Value | Why |
|-----------|-------|-----|
| `--tensor-parallel-size 4` | 4 GPUs | Distributes model across GPUs for performance |
| `--max-model-len 262144` | 256K tokens | Full context window supported by Qwen3.5-9B |
| `--max-num-seqs 1` | 1 concurrent request | Prevents OOM; requests queue sequentially |
| `--max-num-batched-tokens 2048` | 2048 | Limits batch size for memory safety |
| `--gpu-memory-utilization 0.95` | 95% | Leaves headroom for system overhead |
| `--enable-auto-tool-choice` | — | Enables function/tool calling |
| `--tool-call-parser qwen3_coder` | — | Parser for Qwen3's tool call format |

### Step 4: Start the ROCK Gateway

The gateway proxies requests from engineers to vLLM and records traces. Run it in the background with `nohup`:

```bash
cd ~/pluralis-local-agent/ROCK

export ROCK_MODEL_SERVICE_DATA_DIR="$HOME/pluralis-local-agent/ROCK/data"
mkdir -p "$ROCK_MODEL_SERVICE_DATA_DIR"

nohup .venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file examples/agents/open_model_gateway/gateway_config.yaml \
  --host 0.0.0.0 \
  --port 8080 > gateway.log 2>&1 &
```

Follow logs:
```bash
tail -f ~/pluralis-local-agent/ROCK/gateway.log
```

Verify:
```bash
curl http://localhost:8080/health
# {"status":"healthy"}
```

End-to-end test (gateway -> vLLM -> response):
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Rock-User-Id: admin-test" \
  -d '{
    "model": "Qwen/Qwen3.5-9B",
    "messages": [{"role": "user", "content": "Explain reinforcement learning."}],
    "max_tokens": 500
  }'
```

You should get a JSON response with the model's output.

#### Gateway Configuration

The config file is at `ROCK/examples/agents/open_model_gateway/gateway_config.yaml`:

```yaml
host: "0.0.0.0"
port: 8080
proxy_base_url: "http://localhost:8000/v1"    # vLLM endpoint
retryable_status_codes: [429, 500, 502, 503]
request_timeout: 120                           # seconds
trace_db_enabled: true                         # SQLite trace storage
```

All settings can be overridden via CLI flags (`--host`, `--port`, `--proxy-base-url`, etc.).

#### Data Files

After the gateway starts, these files are created in `$ROCK_MODEL_SERVICE_DATA_DIR`:

| File | Purpose |
|------|---------|
| `LLMTraj.jsonl` | Every request/response as a JSON line with full metadata |
| `traces.db` | SQLite database for querying traces via API |

### Step 5: Make the Gateway Reachable

Engineers need to reach port 8080 on your server. Choose one:

| Method | Setup | Engineer uses |
|--------|-------|---------------|
| **Direct** (same network) | Open port 8080 in firewall / security group | `http://<server-ip>:8080` |
| **SSH tunnel** (simplest) | No server changes needed | `ssh -L 8080:localhost:8080 user@server`, then `http://localhost:8080` |
| **Reverse proxy** (nginx) | `proxy_pass http://localhost:8080;` with TLS | `https://gateway.your-domain.com` |
| **VPN** (Tailscale/WireGuard) | Mesh VPN between server and laptops | `http://<tailscale-ip>:8080` |

For AWS EC2: add an inbound rule for TCP port 8080 in the instance's security group, or use the SSH tunnel approach (no security group changes needed).

### Step 6: Onboarding a New Engineer

When a new engineer joins, send them:

1. **This document** — Part B below
2. **How to connect** — one of the following:
   - If they have SSH access (`.pem` key): the SSH config snippet (see Part B, Step 2)
   - If they don't have SSH access: open port 8080 in the EC2 security group and give them the public IP directly (see "Access Without SSH" in Part B)
3. **Their user ID** — their name (e.g. `alice`), used for trace attribution

### Step 7: Managing the Services

```bash
# Follow logs
tail -f ~/pluralis-local-agent/vllm.log     # vLLM logs
tail -f ~/pluralis-local-agent/ROCK/gateway.log  # Gateway logs

# Stop gateway
pkill -f "rock.sdk.model.server.main"

# Stop vLLM
docker stop $(docker ps -q --filter ancestor=vllm/vllm-openai:latest)

# Restart gateway
cd ~/pluralis-local-agent/ROCK
export ROCK_MODEL_SERVICE_DATA_DIR="$HOME/pluralis-local-agent/ROCK/data"
nohup .venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file examples/agents/open_model_gateway/gateway_config.yaml \
  --host 0.0.0.0 --port 8080 > gateway.log 2>&1 &
```

### Step 8: Dashboard

The gateway includes a built-in web dashboard for visualizing traces — no extra services needed.

**URL:** `http://<server-public-ip>:8080/dashboard` (same port as gateway)

The dashboard shows:
- **Summary cards** — total requests, success rate, avg latency, total tokens, unique users
- **Timeline charts** — requests over time, latency trends, token usage (prompt vs completion)
- **Users table** — per-user request counts, errors, avg latency, total tokens, last active. **Click a user** to view their conversations.
- **Sessions table** — per-session groupings with request counts and duration. **Click a session** to view the full conversation thread.
- **Conversation viewer** — modal showing the complete message history (system/user/assistant) for any session or user. Toggle between "Full Messages" and "Compact (Last Turn Only)" views.
- **Recent errors** — latest failed requests with error messages

All times are displayed in **Melbourne timezone** (AEDT/AEST).

Features: time range selector (1h/6h/24h/7d/all), auto-refresh toggle (30s interval).

**Session inference:** Sessions are tracked automatically server-side. The gateway fingerprints the first user message in each iflow conversation to group related requests. No client configuration needed. The timeout is configurable via `session_timeout_minutes` in `gateway_config.yaml` (default: 30 minutes).

**Backfilling existing traces:** If you have traces from before session inference was enabled:
```bash
cd ~/pluralis-local-agent/ROCK
.venv/bin/python -m rock.sdk.model.server.migrate_sessions --db-path data/traces.db
```

### Step 9: Monitoring Traces

#### Via Dashboard (recommended)

Open `http://localhost:8080/dashboard` (SSH tunnel) or `http://<server-public-ip>:8080/dashboard` (direct) in your browser.

#### Via API
```bash
# List recent traces
curl "http://localhost:8080/v1/traces?limit=10"

# Filter by engineer
curl "http://localhost:8080/v1/traces?user_id=alice"

# Filter by status
curl "http://localhost:8080/v1/traces?status=error"

# Date range
curl "http://localhost:8080/v1/traces?start=2026-03-01&end=2026-03-08"

# Full trace detail (includes request/response bodies)
curl "http://localhost:8080/v1/traces/<trace-id>"

# Aggregate stats (total calls, latency, tokens, error rate)
curl "http://localhost:8080/v1/traces/stats"

# Stats for one engineer
curl "http://localhost:8080/v1/traces/stats?user_id=alice"
```

#### Via SQLite
```bash
sqlite3 ~/pluralis-local-agent/ROCK/data/traces.db

-- Calls per engineer
SELECT user_id, COUNT(*) as calls,
       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
       ROUND(AVG(latency_ms)) as avg_latency_ms,
       SUM(total_tokens) as total_tokens
FROM traces
GROUP BY user_id
ORDER BY calls DESC;

-- Recent errors
SELECT trace_id, user_id, error, timestamp
FROM traces
WHERE status = 'error'
ORDER BY timestamp DESC
LIMIT 10;
```

#### Via JSONL file
```bash
# Last 5 traces
tail -5 ~/pluralis-local-agent/ROCK/data/LLMTraj.jsonl | python3 -m json.tool

# Count total traces
wc -l ~/pluralis-local-agent/ROCK/data/LLMTraj.jsonl

# Errors only
grep '"status": "error"' ~/pluralis-local-agent/ROCK/data/LLMTraj.jsonl | python3 -m json.tool
```

---

## Part B: Engineer Setup (End User)

Everything in this section runs on **your local machine** (MacBook / Linux laptop). Nothing here touches the server.

### Prerequisites

| Requirement | Details |
|-------------|---------|
| OS | macOS 10.15+, Ubuntu 20.04+, or Windows 10+ (WSL) |
| Node.js | 22+ ([download](https://nodejs.org/en/download)) |
| RAM | 4GB+ |
| Network | Access to the gateway server (direct, SSH tunnel, or VPN) |

You will need from your backend engineer:
- **Server hostname** — e.g. `ec2-13-221-40-76.compute-1.amazonaws.com`
- **Your user ID** — your name or identifier (e.g. `alice`, `bob`)
- **SSH key** (`.pem` file) — if using SSH tunnel. If you don't have one, see "Access Without SSH" below.

### Step 1: Install iFlow CLI

Pick one method:

```bash
# Option A: One-click install (recommended for macOS/Linux)
bash -c "$(curl -fsSL https://cloud.iflow.cn/iflow-cli/install.sh)"

# Option B: Homebrew (macOS/Linux)
brew tap iflow-ai/iflow-cli
brew install iflow-cli

# Option C: npm (all platforms)
npm install -g @iflow-ai/iflow-cli
```

Verify:
```bash
iflow --version
```

### Step 2: Connect to the Gateway

You need network access to the gateway on port 8080. There are two ways depending on your setup.

#### Option A: SSH Tunnel (you have a .pem key)

If the backend engineer gave you an SSH key file (`.pem`), set up your SSH config first.

**Add this to `~/.ssh/config` on your Mac** (create the file if it doesn't exist):

```
Host gateway-server
    HostName ec2-13-221-40-76.compute-1.amazonaws.com
    User ec2-user
    IdentityFile ~/.ssh/your-key-file.pem
```

Replace:
- `ec2-13-221-40-76.compute-1.amazonaws.com` — the server hostname (get from backend engineer)
- `~/.ssh/your-key-file.pem` — path to the `.pem` file you received

Make sure the key file has correct permissions:
```bash
chmod 400 ~/.ssh/your-key-file.pem
```

**Open the tunnel** (run this in a terminal and keep it open):

```bash
ssh -L 8080:localhost:8080 gateway-server
```

This forwards your local port 8080 to the server's port 8080. The gateway URL is now `http://localhost:8080`.

#### Option B: Direct Access (no .pem key needed)

If the backend engineer has opened port 8080 in the server's firewall/security group, you can connect directly without SSH. No `.pem` file or tunnel needed.

Ask the backend engineer for the **public IP or hostname** of the server. Your gateway URL is:

```
http://<server-public-ip>:8080
```

For example: `http://13.221.40.76:8080`

**Backend engineer**: To enable this, add an inbound rule in the EC2 security group:
- Type: Custom TCP
- Port: 8080
- Source: `0.0.0.0/0` (open to all) or restrict to your team's IP range

#### Verify connectivity

```bash
# If using SSH tunnel:
curl http://localhost:8080/health

# If using direct access:
curl http://<server-public-ip>:8080/health

# Expected output: {"status":"healthy"}
```

If this doesn't work, stop here and troubleshoot connectivity before continuing.

### Step 3: Configure and Login to iFlow

When you run `iflow` for the first time, it will ask you how to authenticate. Follow these steps:

**Run iFlow:**
```bash
iflow
```

**You will see a prompt like:**
```
How would you like to authenticate for this project?

  1. Login with iFlow (recommend)
  2. Use API Key
```

**Select option 2** ("Use API Key" / "Connect via OpenAI-compatible API").

Do NOT pick option 1 — that's iFlow's own cloud service. We use our own server.

**It will then ask you three things:**

| Prompt | What to enter |
|--------|---------------|
| **Base URL** | `http://localhost:8080/v1` (if using SSH tunnel) or `http://<server-ip>:8080/v1` (if direct access). **Must end with `/v1`** |
| **API Key** | Your name — e.g. `alice`, `bob`, `shamane`. This is not a secret; it's used as your user ID for traces. |
| **Model Name** | `Qwen/Qwen3.5-9B` |

After entering these, iFlow saves them to `~/.iflow/settings.json` and you're connected.

#### Alternative: Edit settings.json Directly

If you prefer to skip the interactive login, create the config file manually before running iFlow:

```bash
mkdir -p ~/.iflow
```

Open `~/.iflow/settings.json` in any text editor (nano, vim, VS Code) and paste:

```json
{
  "selectedAuthType": "custom",
  "apiKey": "Gayal",
  "baseUrl": "http://localhost:8080/v1",
  "modelName": "Qwen/Qwen3.5-9B"
}
```

Replace `Gayal` with your actual name/ID. If using direct access instead of SSH tunnel, replace `localhost:8080` with the server's public IP.

Save the file, then run `iflow`.

#### Settings explained

| Field | Value | What it does |
|-------|-------|-------------|
| `selectedAuthType` | `"custom"` | Tells iFlow to use a custom API endpoint instead of its built-in cloud |
| `apiKey` | `"Gayal"` | Sent as your user ID in every request — shows up in traces |
| `baseUrl` | `"http://localhost:8080/v1"` | Where iFlow sends LLM requests. The SSH tunnel makes this reach the real server |
| `modelName` | `"Qwen/Qwen3.5-9B"` | The model hosted on the GPU server |

### Step 4: Test It

```bash
iflow "print hello world in python"
```

If this returns a response, you're connected. The model is Qwen3.5-9B running on the team's GPU server.

### Step 5: Use It on Your Projects

```bash
cd ~/projects/my-app

# Interactive mode
iflow

# One-shot commands
iflow "fix the null pointer exception in auth.py"
iflow "add unit tests for the UserService class"
iflow "refactor the database connection pool to use async"
iflow "explain what the main function does"
```

#### Useful iFlow Commands

| Command | What it does |
|---------|-------------|
| `iflow` | Start interactive mode |
| `iflow "prompt"` | One-shot command |
| `/init` | Scan your project so iFlow understands its structure |
| `/memory` | Manage AI context and instructions |
| `/tools` | Show available tools |
| `/clear` | Clear screen and history |
| `/chat` | Save or restore conversation history |
| `/compress` | Compress context when it gets too long |
| `/stats` | Show session statistics |
| `@path/to/file` | Include a file's content in your prompt |
| `!command` | Run a shell command from within iFlow |
| `/quit` | Exit |

#### Running Modes

iFlow has 4 permission modes you can choose when it starts:

| Mode | Description |
|------|-------------|
| **Default** | AI has no file permissions, only answers questions |
| **Accepting edits** | AI can modify files but nothing else |
| **Plan mode** | AI plans first, you approve, then it executes |
| **YOLO mode** | AI has full permissions (read, write, execute) |

### Step 6: Verify Your Traces

After using iFlow, you can check that your requests are being traced:

```bash
# See your recent traces (replace Gayal with your actual user ID)
curl "http://localhost:8080/v1/traces?user_id=your-name&limit=5"

# See your stats
curl "http://localhost:8080/v1/traces/stats?user_id=Gayal"
```

You can also view traces visually via the dashboard:
- SSH tunnel: `http://localhost:8080/dashboard`
- Direct access: `http://<server-public-ip>:8080/dashboard`

Sessions are automatically tracked server-side — no configuration needed from your end.

---

## Known Limitations

### Context Length (64K tokens)

The model supports up to **262144 tokens** (~256K, input + output combined). This is generous for most tasks, but very large codebases or very long conversations can still hit the limit. If you do:

```
HTTP error! status: 400, body: {"error":{"message":"You passed 65537 input tokens..."}}
```

**How to deal with it:**
- Use `/compress` inside iFlow to shrink the current conversation context
- Start a new conversation (`/clear`) instead of continuing a very long one
- Use `@path/to/file` to include only the specific files you need, not entire directories

### Single Request Queue

The model runs with `--max-num-seqs 1`, meaning it handles one request at a time. If multiple engineers are using it simultaneously, requests will queue and response times will increase. This is a GPU memory limitation.

### Non-Streaming Only

The gateway currently does not support streaming responses (`stream=True`). All responses are returned as a single JSON payload after the model finishes generating.

---

## Troubleshooting

### Server-Side Issues

| Problem | Diagnosis | Fix |
|---------|-----------|-----|
| vLLM won't start | `docker logs <container-id>` | Check GPU drivers, CUDA version, HF_TOKEN |
| vLLM OOM | Logs show CUDA OOM | Reduce `--max-model-len` (try 4096) or `--max-num-batched-tokens` |
| Gateway won't start | `PermissionError: '/data'` | Set `ROCK_MODEL_SERVICE_DATA_DIR` to a writable path |
| Gateway can't reach vLLM | `curl http://localhost:8000/v1/models` fails | Check `docker ps`, restart vLLM container |
| Traces not appearing | Check `trace_db_enabled: true` in config | Also check `$ROCK_MODEL_SERVICE_DATA_DIR` is writable |
| Port 8080 not reachable | `telnet <server-ip> 8080` from laptop | Open port in EC2 security group, or use SSH tunnel |

### Client-Side Issues

| Problem | Diagnosis | Fix |
|---------|-----------|-----|
| `iflow: command not found` | Node.js not installed or npm bin not in PATH | Install Node.js 22+, then `npm install -g @iflow-ai/iflow-cli` |
| `Connection refused` | Gateway not reachable | Check SSH tunnel is running, or verify firewall/security group |
| iFlow asks to "Login with iFlow" | Settings not picked up | Make sure `~/.iflow/settings.json` exists with correct content, or select option 2 and enter details manually |
| `curl /health` works but iFlow doesn't | Wrong settings | Check `~/.iflow/settings.json` — `baseUrl` must end with `/v1` |
| `context length is only 262144 tokens` | Prompt too long | Use `/compress`, start a new chat, or include fewer files. See "Known Limitations" above |
| Slow responses | Expected — single-sequence mode | Model handles one request at a time; requests queue |
| `stream=True not supported` | Gateway is non-streaming only | iFlow should default to non-streaming; check settings |

### Quick Health Check Script

Run this from your laptop to verify the full chain:

```bash
GATEWAY="http://localhost:8080"

echo "=== Health Check ==="
curl -sf "$GATEWAY/health" && echo " OK" || echo " FAIL"

echo "=== Test Request ==="
curl -sf -X POST "$GATEWAY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Rock-User-Id: health-check" \
  -d '{
    "model": "Qwen/Qwen3.5-9B",
    "messages": [{"role":"user","content":"Say OK"}],
    "max_tokens": 5
  }' && echo "" && echo "OK" || echo "FAIL"

echo "=== Trace Check ==="
curl -sf "$GATEWAY/v1/traces?user_id=health-check&limit=1" | python3 -m json.tool
```

---

## Quick Reference

### Server Commands (run on GPU server)

```bash
# Start vLLM (background)
export HF_TOKEN="<token>"
nohup docker run --runtime nvidia --gpus all -p 8000:8000 --ipc=host \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v ~/.cache/huggingface:/root/.cache/huggingface -e HF_TOKEN=$HF_TOKEN \
  vllm/vllm-openai:latest Qwen/Qwen3.5-9B \
  --tensor-parallel-size 4 --max-model-len 262144 --max-num-seqs 1 \
  --max-num-batched-tokens 2048 --gpu-memory-utilization 0.95 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder > vllm.log 2>&1 &

# Start gateway (background)
cd ~/pluralis-local-agent/ROCK
export ROCK_MODEL_SERVICE_DATA_DIR="$HOME/pluralis-local-agent/ROCK/data"
nohup .venv/bin/python -m rock.sdk.model.server.main \
  --type proxy \
  --config-file examples/agents/open_model_gateway/gateway_config.yaml \
  --host 0.0.0.0 --port 8080 > gateway.log 2>&1 &

# Check status
curl http://localhost:8000/v1/models   # vLLM
curl http://localhost:8080/health       # Gateway
docker ps                               # vLLM container

# View traces
curl http://localhost:8080/v1/traces/stats
```

### Engineer Commands (run on your laptop)

```bash
# One-time setup
npm install -g @iflow-ai/iflow-cli

# SSH tunnel (keep this terminal open)
ssh -L 8080:localhost:8080 gateway-server

# First run — iFlow will ask to authenticate:
#   - Pick option 2 (API Key / OpenAI-compatible)
#   - Base URL: http://localhost:8080/v1
#   - API Key: Gayal
#   - Model: Qwen/Qwen3.5-9B (or whatever model is listed at http://localhost:8000/v1/models)

# Daily use
cd ~/my-project
iflow
```
