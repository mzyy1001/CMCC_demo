from __future__ import annotations

from typing import Any, Dict, List, Optional

from tool import (
    get_event,
    edge_get_state,
    edge_batch_assign,
    find_zone_from_event,
    zone_center,
    rect_to_perimeter_waypoints,
    pick_best_drones,
    mk_task_id,
)


def act_patrol(
    trace_id: str,
    num_drones: int,
    event_num: int,
    constraints: dict | None = None,
) -> dict:
    """
    根据 event_list 第 event_num 条事件，派遣普通无人机 D* 去对应 zone 巡检（PATH 围绕）。

    constraints:
      - margin: float (default 3.0) perimeter 外扩
      - loop: bool (default True)
    """
    constraints = constraints or {}

    try:
        ev = get_event(event_num)
        state = edge_get_state()
        zone = find_zone_from_event(state, ev)

        if zone is None:
            return {"ok": False, "error": "Cannot find target zone from event", "event": ev}

        target_xy = zone_center(zone)
        picked = pick_best_drones(state, num=num_drones, want_fire=False, target_xy=target_xy)

        if not picked:
            return {"ok": False, "error": "No available patrol drones (D*)", "event": ev, "zone": zone}

        margin = float(constraints.get("margin", 3.0))
        loop = bool(constraints.get("loop", True))

        waypoints = rect_to_perimeter_waypoints(zone["rect"], margin=margin)

        commands: List[Dict[str, Any]] = []
        for did in picked:
            commands.append({
                "drone_id": did,
                "task": {
                    "type": "PATH",
                    "id": mk_task_id("patrol", trace_id, did),
                    "waypoints": waypoints,
                    "loop": loop,
                }
            })

        resp = edge_batch_assign(commands)

        return {
            "ok": True,
            "trace_id": trace_id,
            "action": "patrol",
            "event_num": event_num,
            "event": ev,
            "zone": zone,
            "picked_drones": picked,
            "edge_response": resp,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
