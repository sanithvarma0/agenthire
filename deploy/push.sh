#!/usr/bin/env bash
# Deploy the current main branch to the server (run from the laptop, in the repository).
#
#   bash deploy/push.sh <server IP>
#
# Builds the site, makes the server's .env from the local one (its own LiveKit agent name,
# so the laptop's worker and the server's never take each other's calls, and a shared
# secret for the worker's events), copies both up and runs deploy/setup.sh there. The code
# itself comes from GitHub, so push your commits first.
#
# It refuses to deploy while a job on the server is calling: a restart cuts a live call.
set -euo pipefail

IP="${1:?usage: bash deploy/push.sh <server IP>}"
HOST="${IP//./-}.sslip.io"
KEY="${KEY_FILE:-$HOME/.ssh/agenthire.pem}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ubuntu@$IP")
cd "$(dirname "$0")/.."
PY=$( [ -x .venv/Scripts/python ] && echo .venv/Scripts/python || echo .venv/bin/python )

if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main 2>/dev/null)" ]; then
  echo "Commit and push first: the server deploys what is on GitHub's main branch." >&2
  exit 1
fi

busy=$(curl -s --max-time 10 "https://$HOST/jobs?limit=20" 2>/dev/null | "$PY" -c '
import json, sys
try:
    jobs = json.load(sys.stdin)
except Exception:
    jobs = []
print(" ".join(j["id"] for j in jobs if j["status"] == "active"
               and j["step"] in ("briefing", "calling", "confirming", "writing", "sourcing", "scoring", "finding", "reporting")))
' || true)
if [ -n "$busy" ]; then
  echo "Not deploying: these jobs are still running on the server: $busy" >&2
  exit 1
fi

npm --prefix web run build
STAGE=$(mktemp -d)
cp -r web/dist "$STAGE/dist"
TOKEN=$("$PY" -c "import secrets; print(secrets.token_hex(24))")
# Windows line endings would leave a stray carriage return at the end of every key on the server.
# TEST_MODE_PIN never goes up: the server stays in test mode, whatever the laptop's switch.
tr -d '\r' < .env | grep -vE '^(AGENT_NAME|INTERNAL_API_TOKEN|BACKEND_URL|DATABASE_PATH|TEST_MODE_PIN)=' > "$STAGE/.env"
cat >> "$STAGE/.env" <<ENV
AGENT_NAME=agenthire-cloud
INTERNAL_API_TOKEN=$TOKEN
BACKEND_URL=http://127.0.0.1:8000
DATABASE_PATH=data/agenthire.db
ENV

"${SSH[@]}" "rm -rf /tmp/agenthire-upload && mkdir -p /tmp/agenthire-upload"
scp -i "$KEY" -q -r "$STAGE/dist" "$STAGE/.env" deploy/setup.sh "ubuntu@$IP:/tmp/agenthire-upload/"
rm -rf "$STAGE"
"${SSH[@]}" "sudo bash /tmp/agenthire-upload/setup.sh $HOST"
echo "Open https://$HOST"
