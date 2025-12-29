#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"

GET_ENDPOINTS=(
  "/state"
  "/runtime/state"
  "/api/state"
  "/cmd/state"
)

get_any() {
  local ep code body
  for ep in "${GET_ENDPOINTS[@]}"; do
    body="$(mktemp)"
    code="$(curl -sS -o "$body" -w "%{http_code}" "${BASE_URL}${ep}" || true)"
    if [[ "$code" == "200" ]]; then
      echo "[OK] GET ${ep}"
      if command -v jq >/dev/null 2>&1; then
        cat "$body" | jq .
      else
        cat "$body"
      fi
      echo
      rm -f "$body"
      return 0
    fi
    rm -f "$body"
  done
  echo "[ERR] GET failed on all endpoints: ${GET_ENDPOINTS[*]}" >&2
  exit 1
}

get_any
