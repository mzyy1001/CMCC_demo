#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"

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

# 默认按你 smoke test 里的 FireZone-A: (42,58,42,58)，margin=4 => (38,62,38,62)
# 你也可以用环境变量覆盖：
#   FIRE_XMIN=... FIRE_XMAX=... FIRE_YMIN=... FIRE_YMAX=... MARGIN=...
FIRE_XMIN="${FIRE_XMIN:-42}"
FIRE_XMAX="${FIRE_XMAX:-58}"
FIRE_YMIN="${FIRE_YMIN:-42}"
FIRE_YMAX="${FIRE_YMAX:-58}"
MARGIN="${MARGIN:-4}"

# 计算扩大后的 perimeter（这里不用 bc，直接写死常见值更稳；如需动态计算你再告诉我）
# 如果你要完全动态计算，我也可以给你一版用 python -c 来算 JSON 的脚本。
PXMIN=$((FIRE_XMIN - MARGIN))
PXMAX=$((FIRE_XMAX + MARGIN))
PYMIN=$((FIRE_YMIN - MARGIN))
PYMAX=$((FIRE_YMAX + MARGIN))

# 4 架无人机从 4 个角“错峰”进入同一个圈（路径点顺序不同）
payload_D1=$(cat <<JSON
{
  "drone_id":"D1",
  "task":{"type":"PATH","loop":true,"waypoints":[
    {"x":${PXMIN},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMIN}}
  ]}
}
JSON
)

payload_D2=$(cat <<JSON
{
  "drone_id":"D2",
  "task":{"type":"PATH","loop":true,"waypoints":[
    {"x":${PXMAX},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMIN}}
  ]}
}
JSON
)

payload_D3=$(cat <<JSON
{
  "drone_id":"D3",
  "task":{"type":"PATH","loop":true,"waypoints":[
    {"x":${PXMAX},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMAX}}
  ]}
}
JSON
)

payload_D4=$(cat <<JSON
{
  "drone_id":"D4",
  "task":{"type":"PATH","loop":true,"waypoints":[
    {"x":${PXMIN},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMIN}},{"x":${PXMAX},"y":${PYMAX}},{"x":${PXMIN},"y":${PYMAX}}
  ]}
}
JSON
)

echo "== Assign fire perimeter patrol =="
echo "Fire rect=(${FIRE_XMIN},${FIRE_XMAX},${FIRE_YMIN},${FIRE_YMAX}), margin=${MARGIN} => perimeter=(${PXMIN},${PXMAX},${PYMIN},${PYMAX})"
post_json "$payload_D1"
post_json "$payload_D2"
post_json "$payload_D3"
post_json "$payload_D4"

echo "Done."
