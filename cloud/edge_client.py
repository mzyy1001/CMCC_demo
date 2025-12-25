from __future__ import annotations
from typing import Dict, List, Tuple

def perimeter_rect(rect: Dict[str, float], margin: float = 4.0) -> List[Dict[str, float]]:
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    xmin -= margin; xmax += margin; ymin -= margin; ymax += margin
    return [
        {"x": xmin, "y": ymin},
        {"x": xmax, "y": ymin},
        {"x": xmax, "y": ymax},
        {"x": xmin, "y": ymax},
        {"x": xmin, "y": ymin},
    ]

def lawnmower_patrol(rect: Dict[str, float], n_stripes: int = 6) -> List[Dict[str, float]]:
    """
    简单“锯齿扫线”覆盖矩形区域，给 patrol 用。
    """
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    n_stripes = max(2, int(n_stripes))

    w = xmax - xmin
    step = w / (n_stripes - 1)

    pts: List[Dict[str, float]] = []
    for i in range(n_stripes):
        x = xmin + i * step
        if i % 2 == 0:
            pts.append({"x": x, "y": ymin})
            pts.append({"x": x, "y": ymax})
        else:
            pts.append({"x": x, "y": ymax})
            pts.append({"x": x, "y": ymin})
    return pts
