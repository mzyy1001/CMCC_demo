from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging

from cloud.config import EDGE_BASE_URL
from cloud.tools import (
    edge_fetch_state, 
    edge_batch, 
    plan_lawnmower, 
    plan_perimeter_rect
)

logger = logging.getLogger("cloud.actions")

def act_patrol(
    trace_id: str,
    num_drones: int,
    patrol_mode: str = "SWEEP",   # "SWEEP" | "PERIMETER"
    constraints: dict | None = None
) -> dict:
    """
    Request a patrol behavior.
    
    Args:
        trace_id: Unique ID for this action request
        num_drones: Number of drones to dispatch
        patrol_mode: "SWEEP" (Lawnmower) or "PERIMETER" (Boundary)
        constraints: Optional args, e.g. {"rect": {...}, "zone_id": "..."}
        
    Returns:
        Result dict with selected drones and dispatch status
    """
    print(f"[ACTION] act_patrol trace={trace_id} n={num_drones} mode={patrol_mode}")
    
    # 1. Fetch current state to find available drones
    try:
        state = edge_fetch_state(EDGE_BASE_URL)
    except Exception as e:
        return {"ok": False, "error": f"Failed to fetch state: {e}"}

    all_drones = state.get("drones", [])
    # Filter for IDLE drones

    idle_drones = [d for d in all_drones if d.get("status") == "IDLE"]
    
    if len(idle_drones) < num_drones:
        return {
            "ok": False, 
            "error": f"Not enough idle drones. Needed {num_drones}, found {len(idle_drones)}",
            "found": [d["id"] for d in idle_drones]
        }
        
    # Select the first N
    selected_drones = idle_drones[:num_drones]
    selected_ids = [d["id"] for d in selected_drones]
    
    # 2. Determine target area (Geometry)

    rect = None
    if constraints:
        rect = constraints.get("rect")
        
    if not rect:
        # Default patrol area (e.g. center of map)
        rect = {"xmin": 20, "xmax": 80, "ymin": 20, "ymax": 80}

    # 3. Plan Path
    waypoints = []
    if patrol_mode.upper() == "PERIMETER":
        waypoints = plan_perimeter_rect(rect)
    else:
        # Default to SWEEP / LAWNMOWER
        # n_stripes depends on rect size, default 4?
        waypoints = plan_lawnmower(rect, n_stripes=4)
        
    if not waypoints:
         return {"ok": False, "error": "Path planning failed (no waypoints generated)"}

    # 4. Dispatch Commands
    commands = []
    for drone_id in selected_ids:
        # Basic strategy: All drones independently patrol the same path 
        # Type PATH
        task = {
            "type": "PATH",
            "waypoints": waypoints,
            "loop": True
        }
        commands.append({
            "drone_id": drone_id,
            "task": task
        })
        
    print(f"[ACTION] Dispatching {len(commands)} commands for patrol.")
    try:
        result = edge_batch(EDGE_BASE_URL, commands)
        return {
            "ok": True,
            "selected_drones": selected_ids,
            "dispatch_result": result
        }
    except Exception as e:
        return {"ok": False, "error": f"Dispatch failed: {e}"}
