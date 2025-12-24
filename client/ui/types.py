from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple, Literal

Color = Tuple[int, int, int]

@dataclass(frozen=True)
class UIVec2:
    x: float
    y: float

@dataclass(frozen=True)
class UIDroneState:
    id: str
    pos: UIVec2
    status: str           # "IDLE" / "NAVIGATING" / "EXECUTING" ...
    battery: float        # 0..100

@dataclass(frozen=True)
class UIZoneState:
    id: str
    name: str
    type: str             # "FIRE_RISK" / "NO_FLY" ...
    # Rect only for now; later you can add polygon if you want
    rect: Tuple[float, float, float, float]  # (xmin, xmax, ymin, ymax)

@dataclass(frozen=True)
class UIEvent:
    ts: float
    level: Literal["INFO", "WARN", "ALERT"]
    title: str
    message: str
    color: Optional[Color] = None

@dataclass
class UIOverlay:
    """
    UI 层覆盖物：不改变仿真，只用于画一些东西（路径、范围、标注等）。
    """
    # A set of named polylines: each is (name, points, color, width)
    polylines: List[Tuple[str, List[UIVec2], Color, int]]
    # Optional marker (e.g., event center)
    marker: Optional[Tuple[str, UIVec2, Color]] = None
    # Optional alert card content
    alert_lines: Optional[List[str]] = None
