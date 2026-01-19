from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

import httpx


# -----------------------------
# Config
# -----------------------------

EDGE_STATE_URL = os.getenv("EDGE_STATE_URL", "http://127.0.0.1:8001/state")
POLL_INTERVAL_S = float(os.getenv("POLL_INTERVAL_S", "2.0"))

OUT_TXT_PATH = os.getenv("EVENT_TXT_PATH", "events_dedup.txt")

MAX_KEYS_IN_MEMORY = int(os.getenv("MAX_KEYS_IN_MEMORY", "50000"))


# -----------------------------
# Dedupe signature
# -----------------------------

def _round(v: Optional[float], ndigits: int = 1) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), ndigits)


def event_signature(ev: Dict[str, Any]) -> Tuple:
    """
    事件去重 key（尽量稳定，不依赖 ts）
    你可以按需求调整：
      - 如果你希望同一个 drone 同一种事件，多次触发也算不同事件 -> 把 ts 也加进去
      - 如果你希望“同位置同类型只算一次” -> 不加 ts
    """
    ev_type = ev.get("type")
    drone_id = ev.get("drone_id")

    pos = ev.get("pos") or {}
    px = _round(pos.get("x"), 1)
    py = _round(pos.get("y"), 1)

    msg = (ev.get("message") or "").strip()[:120]

    sev = _round(ev.get("severity"), 2)
    conf = _round(ev.get("confidence"), 2)

    # payload 可能很大，取一个稳定的简化版 hash
    payload = ev.get("payload")
    payload_str = ""
    if payload is not None:
        try:
            payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)[:200]
        except Exception:
            payload_str = str(payload)[:200]

    # ✅ 不把 ts 放进去 => 同一事件不会重复写入（适合 “去重” 的场景）
    return (ev_type, drone_id, px, py, msg, sev, conf, payload_str)


def load_existing_keys(txt_path: str) -> Set[Tuple]:
    """
    读取已有 txt（每行一个 json），恢复去重 keys，保证重启不重复写。
    """
    keys: Set[Tuple] = set()
    if not os.path.exists(txt_path):
        return keys

    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                keys.add(event_signature(ev))
            except Exception:
                # txt 中如果夹杂了别的行，直接跳过
                continue
    return keys


def append_event(txt_path: str, ev: Dict[str, Any]) -> None:
    """
    以 txt 追加写入（一行一个 json，方便 grep/回放/转 jsonl）
    """
    with open(txt_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


# -----------------------------
# Main loop
# -----------------------------

@dataclass
class Stats:
    pulled: int = 0
    new_events: int = 0
    dup_events: int = 0
    last_print_ts: float = 0.0


async def poll_loop():
    print(f"[event_list] polling {EDGE_STATE_URL} every {POLL_INTERVAL_S:.1f}s")
    print(f"[event_list] output file: {OUT_TXT_PATH}")

    dedup_keys = load_existing_keys(OUT_TXT_PATH)
    print(f"[event_list] loaded {len(dedup_keys)} existing dedup keys")

    stats = Stats()
    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    # graceful shutdown
    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=5.0) as client:
        while not stop_event.is_set():
            t0 = time.time()
            try:
                r = await client.get(EDGE_STATE_URL)
                r.raise_for_status()
                state = r.json()
                stats.pulled += 1

                recent_events = state.get("recent_events") or []
                for ev in recent_events:
                    key = event_signature(ev)
                    if key in dedup_keys:
                        stats.dup_events += 1
                        continue

                    # 新事件：落盘 + 记 key
                    append_event(OUT_TXT_PATH, ev)
                    dedup_keys.add(key)
                    stats.new_events += 1
                    print(f"[event_list] NEW event: {key}")
                    print(f"[event_list] NEW raw: {json.dumps(ev, ensure_ascii=False)}")

                # 防止集合无限膨胀：简单做个裁剪
                if len(dedup_keys) > MAX_KEYS_IN_MEMORY:
                    # ✅ 最简单的策略：直接清一半（不追求完美 LRU）
                    # 你如果要更精致，可以换 OrderedDict 做 LRU
                    dedup_keys = set(list(dedup_keys)[-MAX_KEYS_IN_MEMORY // 2 :])
                    print(f"[event_list] dedup_keys trimmed -> {len(dedup_keys)}")

                # 每隔 10s 打一次统计
                now = time.time()
                if now - stats.last_print_ts > 10:
                    stats.last_print_ts = now
                    print(
                        f"[event_list] pulled={stats.pulled}  new={stats.new_events}  dup={stats.dup_events}  total_keys={len(dedup_keys)}"
                    )


            except Exception as e:
                print(f"[event_list] ERROR: {e}")

            # sleep to keep interval stable
            elapsed = time.time() - t0
            sleep_s = max(0.0, POLL_INTERVAL_S - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                pass

    print("[event_list] stopped.")


def main():
    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
