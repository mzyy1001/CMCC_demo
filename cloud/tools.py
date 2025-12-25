from __future__ import annotations
from typing import Any, Dict, List
import requests

# ---- edge http ----
def edge_fetch_state(edge_base_url: str) -> Dict[str, Any]:
    r = requests.get(f"{edge_base_url}/state", timeout=10)
    r.raise_for_status()
    return r.json()

def edge_assign(edge_base_url: str, drone_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(f"{edge_base_url}/cmd/assign_task", json={"drone_id": drone_id, "task": task}, timeout=10)
    r.raise_for_status()
    return r.json()

def edge_batch(edge_base_url: str, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
    r = requests.post(f"{edge_base_url}/cmd/batch", json={"commands": commands}, timeout=10)
    r.raise_for_status()
    return r.json()

# ---- routing (LLM 不做几何) ----
def plan_perimeter_rect(rect: Dict[str, float], margin: float = 4.0) -> List[Dict[str, float]]:
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    xmin -= margin; xmax += margin; ymin -= margin; ymax += margin
    return [
        {"x": xmin, "y": ymin},
        {"x": xmax, "y": ymin},
        {"x": xmax, "y": ymax},
        {"x": xmin, "y": ymax},
        {"x": xmin, "y": ymin},
    ]

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
