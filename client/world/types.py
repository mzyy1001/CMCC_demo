from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from drone.types import Vec2


class WorldEventType(Enum):
    ENTER_ZONE = auto()
    STAY_IN_ZONE = auto()

    FIRE_DETECTED = auto()
    NO_FLY_VIOLATION = auto()
    SIGNAL_LOSS = auto()


@dataclass(frozen=True)
class WorldEvent:
    """World/Zone 产生的事件（给调度器）。"""
    type: WorldEventType
    ts: float
    pos: Vec2
    drone_id: str
    zone_id: Optional[str] = None
    message: str = ""
    severity: float = 0.0      # demo: 0..1
    confidence: float = 0.0    # demo: 0..1
    payload: Optional[dict] = None
