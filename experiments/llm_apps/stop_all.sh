#!/usr/bin/env bash
# Stop only the processes this launcher started, by the PIDs it recorded.
set -euo pipefail
cd "$(dirname "$0")"
PID_FILE=".run/pids.txt"
if [ ! -f "$PID_FILE" ]; then
  echo "nothing recorded in $PID_FILE"
  exit 0
fi
while read -r name pid; do
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "stopped $name ($pid)"
  else
    echo "$name ($pid) was not running"
  fi
done < "$PID_FILE"
rm -f "$PID_FILE"
