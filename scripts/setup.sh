#!/usr/bin/env bash
# AgentHire in one command: install everything, then start the back end, the voice worker
# and the web app. Run from anywhere inside the repository:
#
#   bash scripts/setup.sh             install, then start all three (Ctrl+C stops them)
#   bash scripts/setup.sh --install   install only
#   bash scripts/setup.sh --start     start only (after an install)
#
# Works on Linux, macOS and Git Bash on Windows. Needs internet and Node.js 20 or newer;
# Python 3.12 is fetched by uv if the machine lacks it. Keys come from .env (created from
# .env.example on the first run; see AGENTS.md section 2). Logs go to data/*.log.
# Ports: back end 8000, web app 5173 (override with BACKEND_PORT and WEB_PORT).
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:---all}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
export BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mStopped: %s\033[0m\n' "$*" >&2; exit 1; }
python_bin() { if [ -x .venv/Scripts/python.exe ]; then echo .venv/Scripts/python.exe; else echo .venv/bin/python; fi; }

install() {
  command -v node >/dev/null 2>&1 || fail "Node.js 20 or newer is needed: https://nodejs.org"
  [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] || fail "Node.js 20 or newer is needed (found $(node -v))."

  if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (the Python package manager)"
    if command -v python3 >/dev/null 2>&1 && python3 -m pip install --user --quiet uv 2>/dev/null; then :
    else curl -LsSf https://astral.sh/uv/install.sh | sh; fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 || fail "uv could not be installed; see https://docs.astral.sh/uv/"
  fi

  say "Python 3.12 environment and packages (pinned in pyproject.toml)"
  [ -x "$(python_bin)" ] || uv venv --python 3.12 .venv
  uv pip install --python .venv -r pyproject.toml

  say "Voice models (speech detection, turn detection), fetched once"
  "$(python_bin)" -m voice.worker download-files >/dev/null

  say "Web app packages"
  npm --prefix web ci --no-audit --no-fund

  if [ ! -f .env ]; then
    cp .env.example .env
    say "Created .env from .env.example"
  fi
  say "Checking the keys in .env (status only, never the values)"
  "$(python_bin)" scripts/check_keys.py || true
}

wait_for() {  # wait_for <url> <name> <log>
  for _ in $(seq 1 90); do
    curl -s -o /dev/null --max-time 2 "$1" && return 0
    sleep 1
  done
  tail -n 20 "$3" >&2 || true
  fail "$2 did not start; the log above is from $3"
}

start() {
  [ -f .env ] || fail "No .env yet: run 'cp .env.example .env' and fill in the keys (AGENTS.md section 2)."
  [ -x "$(python_bin)" ] && [ -d web/node_modules ] || fail "Not installed yet: run 'bash scripts/setup.sh --install' first."
  mkdir -p data
  PY="$(python_bin)"
  # On Ctrl+C or any exit, stop the whole process group: the three servers and their children.
  trap 'trap - INT TERM EXIT; say "Stopping"; kill 0 2>/dev/null' INT TERM EXIT

  say "Back end on http://127.0.0.1:${BACKEND_PORT}"
  PYTHONIOENCODING=utf-8 "$PY" -m uvicorn backend.main:create_app --factory --port "$BACKEND_PORT" > data/backend.log 2>&1 &
  wait_for "http://127.0.0.1:${BACKEND_PORT}/health" "The back end" data/backend.log

  say "Voice worker (registers with LiveKit; restarts itself if LiveKit drops)"
  ( while true; do
      PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 "$PY" -m voice.worker dev >> data/worker.log 2>&1 || true
      echo "=== worker exited $(date '+%H:%M:%S'), restarting in 5 s" >> data/worker.log
      sleep 5
    done ) &

  say "Web app on http://localhost:${WEB_PORT}"
  (cd web && exec npx vite --port "$WEB_PORT" --strictPort) > data/web.log 2>&1 &
  wait_for "http://localhost:${WEB_PORT}/" "The web app" data/web.log

  say "AgentHire is running: open http://localhost:${WEB_PORT}"
  echo "   Logs: data/backend.log, data/worker.log, data/web.log. Ctrl+C stops everything."
  echo "   Journeys to try: AGENTS.md section 7. In test mode every call rings DEMO_ROUTE_PHONE."
  wait
}

case "$MODE" in
  --install) install ;;
  --start) start ;;
  --all) install; start ;;
  *) fail "Unknown option $MODE (use --install, --start or nothing)" ;;
esac
