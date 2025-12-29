#!/usr/bin/env bash
set -euo pipefail

KILL_PORT=9001
HOST="0.0.0.0"
PORT=9001

echo "[INFO] Killing processes listening on port ${KILL_PORT} ..."

# lsof is common on macOS; on Linux it may require `sudo apt-get install lsof`
PIDS=$(lsof -ti tcp:${KILL_PORT} || true)

if [[ -n "${PIDS}" ]]; then
  echo "[INFO] Found PIDs: ${PIDS}"
  # Try graceful first
  kill ${PIDS} || true
  sleep 0.5
  # Force kill anything still alive
  for pid in ${PIDS}; do
    if kill -0 "${pid}" 2>/dev/null; then
      echo "[WARN] PID ${pid} still alive; force killing..."
      kill -9 "${pid}" || true
    fi
  done
else
  echo "[INFO] No process is listening on port ${KILL_PORT}."
fi

echo "[INFO] Starting uvicorn on ${HOST}:${PORT} ..."
exec uvicorn cloud.app:app --host "${HOST}" --port "${PORT}" --reload
