from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from .types import Vec2, DroneEvent, DroneEventType, DroneStatus
from .tasks import TaskType, GoToTask, HoldTask

from .drone import Drone, DroneConfig


@dataclass
class FirefightingConfig(DroneConfig):
    agent_capacity: float = 80.0          # 灭火剂总量（随便定义单位）
    agent_use_per_s: float = 1.5          # 每秒喷洒消耗
    suppress_range_m: float = 6.0         # 距离火点多近才算“能喷到”
    refill_at_home: bool = True           # 回家自动补满


@dataclass
class FirefightingDrone(Drone):
    config: FirefightingConfig = field(default_factory=FirefightingConfig)

    agent_left: float = 80.0              # 当前剩余灭火剂
    suppressing: bool = False             # 是否处于灭火状态
    fire_pos: Optional[Vec2] = None       # 当前灭火目标位置

    def __post_init__(self):
        self.agent_left = float(self.config.agent_capacity)


    def start_suppress_fire(self, fire_pos: Vec2, ts: float) -> List[DroneEvent]:
        """
        一键开始灭火：先飞到火点附近，再切换为 hold 并开始喷洒。
        （也可以改成 orbit 火场边缘）
        """
        self.fire_pos = fire_pos
        self.suppressing = True

        goto = GoToTask(
            id=f"goto-fire-{self.id}-{int(ts*1000)}",
            type=TaskType.GOTO,
            priority=20,
            target=fire_pos,
            arrive_eps=1.0,
        )
        events = self.assign_task(goto, ts)

        events.append(DroneEvent(
            type=DroneEventType.TASK_ASSIGNED,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=f"Fire suppression requested -> {fire_pos}",
            status=self.status,
            task_id=self.task.id if self.task else None
        ))
        return events

    def stop_suppress_fire(self, ts: float, reason: str = "stop suppression") -> List[DroneEvent]:
        self.suppressing = False
        self.fire_pos = None
        return [DroneEvent(
            type=DroneEventType.STATUS_CHANGED,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=reason,
            status=self.status,
            task_id=self.task.id if self.task else None
        )]


    def tick(self, dt: float, ts: float, world_bounds: Optional[Tuple[float, float, float, float]] = None) -> List[DroneEvent]:
        events = super().tick(dt, ts, world_bounds)

        if self.config.refill_at_home and (self.pos - self.home).norm() <= 1e-6:
            if self.agent_left < self.config.agent_capacity:
                self.agent_left = float(self.config.agent_capacity)
                events.append(DroneEvent(
                    type=DroneEventType.HEARTBEAT,
                    drone_id=self.id,
                    pos=self.pos,
                    ts=ts,
                    message="Refilled firefighting agent at home",
                    status=self.status,
                    task_id=self.task.id if self.task else None
                ))

        if self.suppressing and self.fire_pos is not None:
            dist = (self.fire_pos - self.pos).norm()

            if dist <= self.config.suppress_range_m:
                if self.task is None or self.status == DroneStatus.IDLE:
                    hold = HoldTask(
                        id=f"hold-fire-{self.id}-{int(ts*1000)}",
                        type=TaskType.HOLD,
                        priority=30,
                        pos=self.pos,
                        duration_s=None,
                        hold_eps=0.6,
                    )
                    events += self.assign_task(hold, ts)
                    events.append(DroneEvent(
                        type=DroneEventType.HEARTBEAT,
                        drone_id=self.id,
                        pos=self.pos,
                        ts=ts,
                        message="Fire suppression started (holding position)",
                        status=self.status,
                        task_id=self.task.id if self.task else None
                    ))

                if self.agent_left > 0.0:
                    used = min(self.agent_left, self.config.agent_use_per_s * dt)
                    self.agent_left -= used

                    events.append(DroneEvent(
                        type=DroneEventType.HEARTBEAT,
                        drone_id=self.id,
                        pos=self.pos,
                        ts=ts,
                        message=f"Suppressing fire... used={used:.2f}, left={self.agent_left:.2f}",
                        status=self.status,
                        task_id=self.task.id if self.task else None
                    ))

                    if self.agent_left <= 1e-9:
                        self.agent_left = 0.0
                        self.suppressing = False
                        events.append(DroneEvent(
                            type=DroneEventType.HEARTBEAT,
                            drone_id=self.id,
                            pos=self.pos,
                            ts=ts,
                            message="Payload empty. Fire suppression done/paused.",
                            status=self.status,
                            task_id=self.task.id if self.task else None
                        ))

        return events
