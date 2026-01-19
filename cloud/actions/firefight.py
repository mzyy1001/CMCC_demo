from __future__ import annotations

from typing import Any, Dict, List

from tool import (
    get_event,
    edge_get_state,
    edge_batch_assign,
    find_zone_from_event,
    zone_center,
    pick_best_drones,
    mk_task_id,
)


def act_firefight(
    trace_id: str,
    num_drones: int,
    event_num: int,
    constraints: dict | None = None,
) -> dict:
    """
    根据 event_list 第 event_num 条事件，派遣灭火无人机 FD* 去对应 fire zone（GOTO 到 zone 中心）。

    constraints:
      - arrive_eps: float (default 1.2)
    """
    constraints = constraints or {}

    try:
        ev = get_event(event_num)
        state = edge_get_state()
        zone = find_zone_from_event(state, ev)

        if zone is None:
            return {"ok": False, "error": "Cannot find target zone from event", "event": ev}

        cx, cy = zone_center(zone)

        picked = pick_best_drones(state, num=num_drones, want_fire=True, target_xy=(cx, cy))
        if not picked:
            return {"ok": False, "error": "No available firefighting drones (FD*)", "event": ev, "zone": zone}

        arrive_eps = float(constraints.get("arrive_eps", 1.2))

        commands: List[Dict[str, Any]] = []
        for did in picked:
            commands.append({
                "drone_id": did,
                "task": {
                    "type": "GOTO",
                    "id": mk_task_id("firefight", trace_id, did),
                    "target": {"x": cx, "y": cy},
                    "arrive_eps": arrive_eps,
                }
            })

        resp = edge_batch_assign(commands)

        return {
            "ok": True,
            "trace_id": trace_id,
            "action": "firefight",
            "event_num": event_num,
            "event": ev,
            "zone": zone,
            "picked_drones": picked,
            "edge_response": resp,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
