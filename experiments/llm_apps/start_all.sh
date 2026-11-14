#!/usr/bin/env bash
# Start the four local LLM test apps (A1-A4) and remember only their PIDs.
#
# Local test subjects only: they bind 127.0.0.1 by default and must never be
# exposed to the internet. Set LLM_APPS_HOST=0.0.0.0 only when GreenLit runs in
# Docker and reaches them through host.docker.internal.
set -euo pipefail
cd "$(dirname "$0")"

MODE="${APP_MODE:-guarded}"
HOST="${LLM_APPS_HOST:-127.0.0.1}"
PY="${PYTHON:-python}"
VENV_PY=".venv/Scripts/python.exe"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
RUN_DIR=".run"
PID_FILE="$RUN_DIR/pids.txt"
mkdir -p "$RUN_DIR"

port_free() {
  "$PY" - "$1" <<'PY'
import socket, sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    print("busy")
finally:
    sock.close()
PY
}

for port in 9111 9112 9113 9114; do
  if [ -n "$(port_free "$port")" ]; then
    echo "port $port is already in use; refusing to start" >&2
    exit 1
  fi
done

if [ ! -x "$VENV_PY" ]; then
  echo "A4 needs the app's own virtualenv: python -m venv .venv && .venv/Scripts/python -m pip install 'mcp<2'" >&2
  exit 1
fi

: > "$PID_FILE"
start() {
  local name="$1"; shift
  "$@" >>"$RUN_DIR/$name.log" 2>&1 &
  local pid=$!
  echo "$name $pid" >>"$PID_FILE"
}

start support-bot "$PY" support_bot/app.py --host "$HOST" --port 9111
start docs-rag "$PY" docs_rag/app.py --host "$HOST" --port 9112
start stream-bot "$PY" stream_bot/app.py --host "$HOST" --port 9113
start tool-agent "$VENV_PY" tool_agent/server.py --host "$HOST" --port 9114

for _ in $(seq 1 60); do
  if "$PY" - <<'PY'
import sys, urllib.request
for port in (9111, 9112, 9113):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
    except Exception:
        sys.exit(1)
sys.exit(0)
PY
  then
    break
  fi
  sleep 0.5
done

echo "mode=$MODE (APP_MODE) provider=${LLM_PROVIDER:-ollama} bind=$HOST"
echo "A1 support-bot  http://$HOST:9111/"
echo "A2 docs-rag     http://$HOST:9112/   (RAG_MODE=${RAG_MODE:-normal})"
echo "A3 stream-bot   http://$HOST:9113/  /sse  /ndjson  /text"
echo "A4 tool-agent   http://$HOST:9114/mcp  (MCP, tool: ask_assistant or calculator)"
echo "PIDs in $PID_FILE; stop with ./stop_all.sh"
