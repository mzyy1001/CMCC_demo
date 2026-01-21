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
    plan_lawnmower,
)



def act_patrol(
    trace_id: str,
    num_drones: int,
    patrol_mode: str = "SWEEP",
    event_num: int | None = None,
    constraints: dict | None = None,
) -> dict:
    """
    派遣普通无人机 D* 进行全图（或指定区域）扫描巡逻（Lawnmower）。

    Args:
      event_num: int (optional) - Read context from events_dedup.txt
      patrol_mode: "SWEEP" (default)
      constraints: rect, n_stripes, loop
    """
    constraints = constraints or {}

    try:
        # Resolve Event for Context (Optional)
        if event_num is not None:
            try:
                ev = get_event(event_num)
                # Future: Could use ev['pos'] to set default rect center
            except Exception:
                pass

        state = edge_get_state()
        
        # Default scan area 0-100 if not provided
        rect = constraints.get("rect", {"xmin": 0, "xmax": 100, "ymin": 0, "ymax": 100})
        n_stripes = int(constraints.get("n_stripes", 6))
        loop = bool(constraints.get("loop", True))

        # Use center of rect for drone selection proximity
        cx = (rect["xmin"] + rect["xmax"]) / 2
        cy = (rect["ymin"] + rect["ymax"]) / 2

        picked = pick_best_drones(state, num=num_drones, want_fire=False, target_xy=(cx, cy))

        if not picked:
            return {"ok": False, "error": "No available patrol drones (D*)"}

        waypoints = plan_lawnmower(rect, n_stripes=n_stripes)

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
            "picked_drones": picked,
            "edge_response": resp,
            "waypoints": waypoints 
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
