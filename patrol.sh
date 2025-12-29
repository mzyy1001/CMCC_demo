#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"

# 你代码里提示过 /cmd/assign_task；这里做几个常见备选
POST_ENDPOINTS=(
  "/cmd/assign_task"
  "/cmd/assign"
  "/cmd/task/assign"
)

post_json() {
  local payload="$1"
  local ep code body
  for ep in "${POST_ENDPOINTS[@]}"; do
    body="$(mktemp)"
    code="$(curl -sS -o "$body" -w "%{http_code}" \
      -X POST "${BASE_URL}${ep}" \
      -H "Content-Type: application/json" \
      --data-binary "$payload" || true)"
    if [[ "$code" == "200" || "$code" == "201" ]]; then
      echo "[OK] POST ${ep}"
      cat "$body"; echo
      rm -f "$body"
      return 0
    fi
    rm -f "$body"
  done
  echo "[ERR] POST failed on all endpoints: ${POST_ENDPOINTS[*]}" >&2
  exit 1
}

# --- 4 个分区蛇形：世界 0..100
# D1: 左下  (x: 5..50,  y: 5..50)
# D2: 右下  (x: 50..95, y: 5..50)
# D3: 左上  (x: 5..50,  y: 50..95)
# D4: 右上  (x: 50..95, y: 50..95)

payload_D1='{
  "drone_id":"D1",
  "task":{
    "type":"PATH",
    "loop":true,
    "waypoints":[
      {"x":5,"y":5},{"x":50,"y":5},
      {"x":50,"y":15},{"x":5,"y":15},
      {"x":5,"y":25},{"x":50,"y":25},
      {"x":50,"y":35},{"x":5,"y":35},
      {"x":5,"y":45},{"x":50,"y":45}
    ]
  }
}'

payload_D2='{
  "drone_id":"D2",
  "task":{
    "type":"PATH",
    "loop":true,
    "waypoints":[
      {"x":50,"y":5},{"x":95,"y":5},
      {"x":95,"y":15},{"x":50,"y":15},
      {"x":50,"y":25},{"x":95,"y":25},
      {"x":95,"y":35},{"x":50,"y":35},
      {"x":50,"y":45},{"x":95,"y":45}
    ]
  }
}'

payload_D3='{
  "drone_id":"D3",
  "task":{
    "type":"PATH",
    "loop":true,
    "waypoints":[
      {"x":5,"y":50},{"x":50,"y":50},
      {"x":50,"y":60},{"x":5,"y":60},
      {"x":5,"y":70},{"x":50,"y":70},
      {"x":50,"y":80},{"x":5,"y":80},
      {"x":5,"y":90},{"x":50,"y":90}
    ]
  }
}'

payload_D4='{
  "drone_id":"D4",
  "task":{
    "type":"PATH",
    "loop":true,
    "waypoints":[
      {"x":50,"y":50},{"x":95,"y":50},
      {"x":95,"y":60},{"x":50,"y":60},
      {"x":50,"y":70},{"x":95,"y":70},
      {"x":95,"y":80},{"x":50,"y":80},
      {"x":50,"y":90},{"x":95,"y":90}
    ]
  }
}'

echo "== Start snake patrol =="
post_json "$payload_D1"
post_json "$payload_D2"
post_json "$payload_D3"
post_json "$payload_D4"

echo "Done."
