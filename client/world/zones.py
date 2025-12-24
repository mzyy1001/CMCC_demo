from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, List, Tuple
import random

from drone.types import Vec2
from .types import WorldEvent, WorldEventType


class ZoneType(Enum):
    FIRE_RISK = auto()
    NO_FLY = auto()
    SIGNAL_LOSS = auto()
    INFO = auto()


class TriggerMode(Enum):
    ON_ENTER = auto()   
    ON_STAY = auto()    


@dataclass(frozen=True)
class Rect:
    xmin: float
    xmax: float
    ymin: float
    ymax: float

    def contains(self, p: Vec2) -> bool:
        return (self.xmin <= p.x <= self.xmax) and (self.ymin <= p.y <= self.ymax)


@dataclass
class ZoneEventPolicy:
    """
    demo 简化：每种 zone 定义自己的事件触发策略
    - trigger_mode: 进入触发还是停留触发
    - cooldown_s: ON_STAY 时的最小触发间隔
    - probability: 触发概率（用于信号丢失等）
    """
    trigger_mode: TriggerMode = TriggerMode.ON_ENTER
    cooldown_s: float = 0.0
    probability: float = 1.0
    severity: float = 0.5
    confidence: float = 0.7


@dataclass
class Zone:
    id: str
    name: str
    type: ZoneType
    rect: Rect
    policy: ZoneEventPolicy = field(default_factory=ZoneEventPolicy)

    def contains(self, p: Vec2) -> bool:
        return self.rect.contains(p)

    def produce_events(
        self,
        *,
        drone_id: str,
        pos: Vec2,
        ts: float,
        entering: bool,
        last_fired_ts: Optional[float],
        rng: random.Random
    ) -> Tuple[List[WorldEvent], Optional[float]]:
        """
        返回 (events, new_last_fired_ts)
        """
        events: List[WorldEvent] = []

        # decide whether eligible to fire
        if self.policy.trigger_mode == TriggerMode.ON_ENTER and not entering:
            return events, last_fired_ts

        if self.policy.trigger_mode == TriggerMode.ON_STAY:
            if last_fired_ts is not None and (ts - last_fired_ts) < self.policy.cooldown_s:
                return events, last_fired_ts

        # stochastic gate
        if rng.random() > self.policy.probability:
            return events, last_fired_ts

        # map zone type -> world event type
        if self.type == ZoneType.FIRE_RISK:
            etype = WorldEventType.FIRE_DETECTED
            msg = f"Fire suspected in zone {self.name}"
        elif self.type == ZoneType.NO_FLY:
            etype = WorldEventType.NO_FLY_VIOLATION
            msg = f"No-fly zone violation: {self.name}"
        elif self.type == ZoneType.SIGNAL_LOSS:
            etype = WorldEventType.SIGNAL_LOSS
            msg = f"Signal loss triggered in zone {self.name}"
        else:
            etype = WorldEventType.ENTER_ZONE if entering else WorldEventType.STAY_IN_ZONE
            msg = f"Zone trigger: {self.name}"

        events.append(WorldEvent(
            type=etype,
            ts=ts,
            pos=pos,
            drone_id=drone_id,
            zone_id=self.id,
            message=msg,
            severity=self.policy.severity,
            confidence=self.policy.confidence,
            payload={"zone_type": self.type.name, "zone_name": self.name, "entering": entering}
        ))
        return events, ts
