#!/usr/bin/env bash
set -euo pipefail

CLOUD="${CLOUD_URL:-http://127.0.0.1:9001}"

RAW="$(curl -sS -X POST "$CLOUD/sessions")"
echo "[sessions] $RAW"

SID="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["session_id"])' "$RAW")"
echo "SID=$SID"

curl -sS -X POST "$CLOUD/sessions/$SID/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"开始巡逻"}'
echo
