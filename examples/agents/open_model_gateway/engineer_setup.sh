#!/usr/bin/env bash
# Engineer onboarding script for ROCK Model Gateway + iflow CLI
#
# Usage:
#   ./engineer_setup.sh <GATEWAY_URL> <USER_ID>
#
# Example:
#   ./engineer_setup.sh http://10.0.0.1:8080 alice

set -euo pipefail

GATEWAY_URL="${1:?Usage: $0 <GATEWAY_URL> <USER_ID>}"
USER_ID="${2:?Usage: $0 <GATEWAY_URL> <USER_ID>}"
MODEL_NAME="Qwen/Qwen3.5-35B-A3B"

echo "=== ROCK Model Gateway — Engineer Setup ==="
echo "Gateway:  ${GATEWAY_URL}"
echo "User ID:  ${USER_ID}"
echo "Model:    ${MODEL_NAME}"
echo ""

# 1. Validate gateway health
echo "Checking gateway health..."
if ! curl -sf "${GATEWAY_URL}/health" > /dev/null 2>&1; then
    echo "ERROR: Gateway at ${GATEWAY_URL} is not reachable."
    echo "Make sure the gateway is running and the URL is correct."
    exit 1
fi
echo "Gateway is healthy."

# 2. Install iflow CLI if not present
if ! command -v iflow &> /dev/null; then
    echo "Installing iflow CLI..."
    pip install iflow-cli
else
    echo "iflow CLI already installed: $(iflow --version 2>/dev/null || echo 'unknown version')"
fi

# 3. Configure shell environment
SHELL_RC=""
if [[ -f "$HOME/.zshrc" ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

cat <<EOF

Add the following to your shell profile (${SHELL_RC:-~/.bashrc}):

  export IFLOW_BASE_URL="${GATEWAY_URL}/v1"
  export IFLOW_MODEL_NAME="${MODEL_NAME}"
  export IFLOW_API_KEY="${USER_ID}"

Then run: source ${SHELL_RC:-~/.bashrc}

EOF

# 4. Test with a simple request
echo "Sending test request..."
RESPONSE=$(curl -sf -X POST "${GATEWAY_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-Rock-User-Id: ${USER_ID}" \
    -H "X-Rock-Session-Id: setup-test" \
    -d '{
        "model": "'"${MODEL_NAME}"'",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 10
    }' 2>&1) && {
    echo "Test request succeeded."
    echo "Response: ${RESPONSE}"
} || {
    echo "WARNING: Test request failed (model may not be loaded yet). Setup is complete — try again later."
}

echo ""
echo "Setup complete."
