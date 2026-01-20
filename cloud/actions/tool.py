from __future__ import annotations

import json
import os
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx


# -----------------------------
# Config
# -----------------------------

EDGE_BASE_URL = os.getenv("EDGE_BASE_URL", "http://127.0.0.1:8001")
EVENT_LIST_TXT = os.getenv("EVENT_LIST_TXT", "events_dedup.txt")


# -----------------------------
# Event list
# -----------------------------

def load_events(path: str = EVENT_LIST_TXT) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return events

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def get_event(event_num: int, path: str = EVENT_LIST_TXT) -> Dict[str, Any]:
    """
    event_num: 1-based index
    """
    events = load_events(path)
    if not events:
        raise ValueError(f"event_list is empty: {path}")

    idx = event_num - 1
    if idx < 0 or idx >= len(events):
        raise ValueError(f"event_num out of range: {event_num}, total={len(events)}")

    return events[idx]


# -----------------------------
# Edge API
# -----------------------------

def edge_get_state() -> Dict[str, Any]:
    with httpx.Client(timeout=5.0) as client:
        r = client.get(f"{EDGE_BASE_URL}/state")
        r.raise_for_status()
        return r.json()


def edge_batch_assign(commands: List[Dict[str, Any]]) -> Dict[str, Any]:
    with httpx.Client(timeout=8.0) as client:
        r = client.post(f"{EDGE_BASE_URL}/cmd/batch", json={"commands": commands})
        r.raise_for_status()
        return r.json()


# -----------------------------
# Zone helpers
# -----------------------------

def zone_center(zone: Dict[str, Any]) -> Tuple[float, float]:
    rect = zone["rect"]
    xmin, xmax = float(rect["xmin"]), float(rect["xmax"])
    ymin, ymax = float(rect["ymin"]), float(rect["ymax"])
    return (xmin + xmax) / 2.0, (ymin + ymax) / 2.0


def rect_to_perimeter_waypoints(rect: Dict[str, Any], margin: float = 3.0) -> List[Dict[str, float]]:
    xmin = float(rect["xmin"]) - margin
    xmax = float(rect["xmax"]) + margin
    ymin = float(rect["ymin"]) - margin
    ymax = float(rect["ymax"]) + margin
    return [
        {"x": xmin, "y": ymin},
        {"x": xmax, "y": ymin},
        {"x": xmax, "y": ymax},
        {"x": xmin, "y": ymax},
        {"x": xmin, "y": ymin},
    ]


def find_zone_from_event(state: Dict[str, Any], ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    优先使用 event.payload.zone_name 精确匹配
    """
    zones = state.get("zones", []) or []
    payload = ev.get("payload") or {}
    zone_name = payload.get("zone_name")

    if zone_name:
        for z in zones:
            if z.get("name") == zone_name:
                return z

    # fallback：找第一个 FIRE_RISK
    for z in zones:
        if (z.get("type") or "") == "FIRE_RISK":
            return z

    return None


# -----------------------------
# Drone picking (idle + distance)
# -----------------------------

def is_fire_drone(drone_id: str) -> bool:
    return drone_id.upper().startswith("FD")


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _idle_flag(dr: Dict[str, Any]) -> int:
    """
    0 = idle best, 1 = busy
    """
    status = (dr.get("status") or "").upper()
    task = dr.get("task")
    idle = (status in ("IDLE", "HOVER", "READY")) and (task is None)
    return 0 if idle else 1


def pick_best_drones(
    state: Dict[str, Any],
    num: int,
    want_fire: bool,
    target_xy: Optional[Tuple[float, float]] = None,
) -> List[str]:
    """
    挑选“最近最空闲”的无人机：
      1) idle 优先
      2) 离 target 更近优先（如果提供 target_xy）
      3) 电量更高优先
    """
    drones = state.get("drones", []) or []

    if want_fire:
        cand = [d for d in drones if is_fire_drone(d.get("id", ""))]
    else:
        cand = [d for d in drones if not is_fire_drone(d.get("id", ""))]

    if not cand:
        return []

    def key_fn(d: Dict[str, Any]):
        idle = _idle_flag(d)
        battery = float(d.get("battery", 0.0))
        if target_xy is None:
            dist = 0.0
        else:
            pos = d.get("pos") or {}
            dx, dy = float(pos.get("x", 0.0)), float(pos.get("y", 0.0))
            dist = _dist((dx, dy), target_xy)
        return (idle, dist, -battery)

    cand.sort(key=key_fn)
    return [d["id"] for d in cand[:num]]



def mk_task_id(prefix: str, trace_id: str, drone_id: str) -> str:
    return f"{prefix}_{trace_id}_{drone_id}_{int(time.time())}"


def plan_lawnmower(rect: Dict[str, float], n_stripes: int = 6) -> List[Dict[str, float]]:
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    n_stripes = max(2, int(n_stripes))
    step = (xmax - xmin) / (n_stripes - 1)
    pts: List[Dict[str, float]] = []
    for i in range(n_stripes):
        x = xmin + i * step
        if i % 2 == 0:
            pts += [{"x": x, "y": ymin}, {"x": x, "y": ymax}]
        else:
            pts += [{"x": x, "y": ymax}, {"x": x, "y": ymin}]
    return pts
