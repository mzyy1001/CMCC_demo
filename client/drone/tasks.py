from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional

from .types import Vec2


class TaskType(Enum):
    """
    通用控制意图（LLM 友好）：
    - PATH: 跟随航点序列（巡查/覆盖/接管都是 PATH）
    - GOTO: 飞向某个目标点
    - ORBIT: 围绕某个中心点绕圈（扫描/调查/盘旋）
    - HOLD: 在某个点附近悬停
    - RETURN_HOME: 返航
    """
    PATH = auto()
    GOTO = auto()
    ORBIT = auto()
    HOLD = auto()
    RETURN_HOME = auto()


@dataclass
class Task:
    id: str
    type: TaskType
    priority: int = 0
    # 可选：task 层覆盖 drone 默认速度（None 表示用 drone.config.speed_mps）
    speed_mps: Optional[float] = None


@dataclass
class PathTask(Task):
    waypoints: List[Vec2] = None
    loop: bool = True
    cursor: int = 0
    arrive_eps: float = 0.5  # 到点阈值（米），更稳


@dataclass
class GoToTask(Task):
    target: Vec2 = Vec2(0.0, 0.0)
    arrive_eps: float = 0.5


@dataclass
class OrbitTask(Task):
    center: Vec2 = Vec2(0.0, 0.0)
    radius: float = 6.0
    # duration_s=None 表示无限绕圈，直到调度器下新任务
    duration_s: Optional[float] = 15.0
    elapsed_s: float = 0.0


@dataclass
class HoldTask(Task):
    pos: Vec2 = Vec2(0.0, 0.0)
    duration_s: Optional[float] = 5.0
    elapsed_s: float = 0.0
    # hold_eps 控制允许的小偏差（比如控制误差/漂移容忍）
    hold_eps: float = 0.8


@dataclass
class ReturnHomeTask(Task):
    home: Vec2 = Vec2(0.0, 0.0)
    arrive_eps: float = 0.8
