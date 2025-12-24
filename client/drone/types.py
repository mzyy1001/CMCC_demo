from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> "Vec2":
        return Vec2(self.x * k, self.y * k)

    def norm(self) -> float:
        return (self.x * self.x + self.y * self.y) ** 0.5

    def normalized(self) -> "Vec2":
        n = self.norm()
        if n <= 1e-9:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / n, self.y / n)


class DroneStatus(Enum):
    """
    - IDLE: 无任务/等待
    - NAVIGATING: 执行 goto/path 这类移动
    - EXECUTING: 在某区域执行（hold/orbit/scan 等）
    - RETURNING: 返航
    - OFFLINE: 离线（调度器应接管）
    - FAILED: 不可用（可选）
    """
    IDLE = auto()
    NAVIGATING = auto()
    EXECUTING = auto()
    RETURNING = auto()
    OFFLINE = auto()
    FAILED = auto()


class DroneEventType(Enum):
    STATUS_CHANGED = auto()
    TASK_ASSIGNED = auto()
    TASK_COMPLETED = auto()
    BATTERY_LOW = auto()
    OFFLINE = auto()
    HEARTBEAT = auto()


@dataclass(frozen=True)
class DroneEvent:
    """Drone 内部产生的事件（给调度器/日志/UI）。"""
    type: DroneEventType
    drone_id: str
    pos: Vec2
    ts: float
    message: str
    status: Optional[DroneStatus] = None
    task_id: Optional[str] = None
