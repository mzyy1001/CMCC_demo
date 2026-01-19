from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from .types import Vec2, DroneStatus, DroneEvent, DroneEventType
from .tasks import (
    Task, TaskType,
    PathTask, GoToTask, OrbitTask, HoldTask, ReturnHomeTask
)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _move_towards(pos: Vec2, target: Vec2, max_step: float) -> Tuple[Vec2, bool]:
    """
    返回 (new_pos, arrived)
    """
    delta = target - pos
    dist = delta.norm()
    if dist <= max_step or dist <= 1e-9:
        return target, True
    step = delta.normalized() * max_step
    return pos + step, False


@dataclass
class DroneConfig:
    speed_mps: float = 8.0
    battery_capacity: float = 100.0
    battery_drain_per_s: float = 0.12
    battery_low_threshold: float = 20.0
    heartbeat_period_s: float = 1.0
    investigate_orbit_points: int = 12  # ORBIT 分段数


@dataclass
class Drone:
    id: str
    pos: Vec2
    home: Vec2
    config: DroneConfig = field(default_factory=DroneConfig)

    status: DroneStatus = DroneStatus.IDLE
    battery: float = 100.0

    task: Optional[Task] = None

    last_heartbeat_ts: float = 0.0
    last_seen_ts: float = 0.0

    _orbit_idx: int = 0

    # ---------------- public API ----------------

    def assign_task(self, task: Task, ts: float) -> List[DroneEvent]:
        """
        调度器/LLM 下发通用任务（不含业务语义）。
        """
        self.task = task

        # 兼容原来的 DroneStatus：这里把 ASSIST 当作“机动/导航中”
        new_status = {
            TaskType.PATH: DroneStatus.NAVIGATING,
            TaskType.GOTO: DroneStatus.NAVIGATING,
            TaskType.ORBIT: DroneStatus.EXECUTING,
            TaskType.HOLD: DroneStatus.EXECUTING,
            TaskType.RETURN_HOME: DroneStatus.RETURNING,
        }.get(task.type, DroneStatus.IDLE)

        events: List[DroneEvent] = []
        events += self._set_status(new_status, ts, f"Task assigned: {task.type.name}")
        events.append(DroneEvent(
            type=DroneEventType.TASK_ASSIGNED,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=f"Assigned task={task.type.name}",
            status=self.status,
            task_id=task.id
        ))
        return events

    def set_offline(self, ts: float, reason: str = "offline") -> List[DroneEvent]:
        self.task = None
        events = self._set_status(DroneStatus.OFFLINE, ts, reason)
        events.append(DroneEvent(
            type=DroneEventType.OFFLINE,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=reason,
            status=self.status
        ))
        return events

    def tick(self, dt: float, ts: float, world_bounds: Optional[Tuple[float, float, float, float]] = None) -> List[DroneEvent]:
        """
        dt: 秒
        ts: 当前仿真时间（秒）
        world_bounds: (xmin, xmax, ymin, ymax) 位置边界限制（可选）
        """
        events: List[DroneEvent] = []

        if self.status in (DroneStatus.OFFLINE, DroneStatus.FAILED):
            return events

        # battery drain
        self.battery = _clamp(
            self.battery - self.config.battery_drain_per_s * dt,
            0.0,
            self.config.battery_capacity
        )

        # battery low -> force return (override task)
        if self.battery <= self.config.battery_low_threshold and self.status not in (DroneStatus.RETURN, DroneStatus.IDLE):
            return_task = ReturnHomeTask(
                id=f"return-{self.id}-{int(ts*1000)}",
                type=TaskType.RETURN_HOME,
                priority=10,
                home=self.home
            )
            events += self.assign_task(return_task, ts)
            events.append(DroneEvent(
                type=DroneEventType.BATTERY_LOW,
                drone_id=self.id,
                pos=self.pos,
                ts=ts,
                message=f"Battery low: {self.battery:.1f}%",
                status=self.status,
                task_id=self.task.id if self.task else None
            ))

        # execute task
        if self.task is None:
            if self.status != DroneStatus.IDLE:
                events += self._set_status(DroneStatus.IDLE, ts, "No task")
        else:
            events += self._step_task(dt, ts)

        # clamp to bounds
        if world_bounds is not None:
            xmin, xmax, ymin, ymax = world_bounds
            self.pos = Vec2(_clamp(self.pos.x, xmin, xmax), _clamp(self.pos.y, ymin, ymax))

        # heartbeat
        if ts - self.last_heartbeat_ts >= self.config.heartbeat_period_s:
            self.last_heartbeat_ts = ts
            self.last_seen_ts = ts
            events.append(DroneEvent(
                type=DroneEventType.HEARTBEAT,
                drone_id=self.id,
                pos=self.pos,
                ts=ts,
                message="heartbeat",
                status=self.status,
                task_id=self.task.id if self.task else None
            ))

        return events

    def _set_status(self, new_status: DroneStatus, ts: float, reason: str) -> List[DroneEvent]:
        if new_status == self.status:
            return []
        self.status = new_status
        return [DroneEvent(
            type=DroneEventType.STATUS_CHANGED,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=reason,
            status=new_status,
            task_id=self.task.id if self.task else None
        )]

    def _effective_speed(self) -> float:
        if self.task is None or self.task.speed_mps is None:
            return self.config.speed_mps
        return max(0.1, float(self.task.speed_mps))

    def _step_task(self, dt: float, ts: float) -> List[DroneEvent]:
        assert self.task is not None
        t = self.task
        events: List[DroneEvent] = []

        max_step = self._effective_speed() * dt

        # -------- PATH --------
        if isinstance(t, PathTask):
            if not t.waypoints:
                events += self._complete_task(ts, "Empty path")
                return events

            wp = t.waypoints[t.cursor]
            # 使用 arrive_eps：更稳定，避免抖动卡在点附近
            delta = wp - self.pos
            if delta.norm() <= t.arrive_eps:
                self.pos = wp
                arrived = True
            else:
                self.pos, arrived = _move_towards(self.pos, wp, max_step)

            if arrived:
                t.cursor += 1
                if t.cursor >= len(t.waypoints):
                    if t.loop:
                        t.cursor = 0
                    else:
                        events += self._complete_task(ts, "Path finished")
            return events

        # -------- GOTO --------
        if isinstance(t, GoToTask):
            delta = t.target - self.pos
            if delta.norm() <= t.arrive_eps:
                self.pos = t.target
                events += self._complete_task(ts, "Arrived target")
                return events
            self.pos, _ = _move_towards(self.pos, t.target, max_step)
            return events

        # -------- ORBIT --------
        if isinstance(t, OrbitTask):
            import math
            orbit_n = max(4, self.config.investigate_orbit_points)
            angle = 2.0 * math.pi * (self._orbit_idx % orbit_n) / orbit_n
            orbit_target = Vec2(
                t.center.x + t.radius * math.cos(angle),
                t.center.y + t.radius * math.sin(angle),
            )

            self.pos, arrived = _move_towards(self.pos, orbit_target, max_step)
            if arrived:
                self._orbit_idx = (self._orbit_idx + 1) % orbit_n

            t.elapsed_s += dt
            if t.duration_s is not None and t.elapsed_s >= t.duration_s:
                events += self._complete_task(ts, "Orbit done")
            return events

        # -------- HOLD --------
        if isinstance(t, HoldTask):
            # hold：允许有一点漂移，然后拉回
            delta = t.pos - self.pos
            if delta.norm() > t.hold_eps:
                self.pos, _ = _move_towards(self.pos, t.pos, max_step)

            t.elapsed_s += dt
            if t.duration_s is not None and t.elapsed_s >= t.duration_s:
                events += self._complete_task(ts, "Hold done")
            return events

        # -------- RETURN_HOME --------
        if isinstance(t, ReturnHomeTask):
            delta = t.home - self.pos
            if delta.norm() <= t.arrive_eps:
                self.pos = t.home
                events += self._complete_task(ts, "Arrived home")
                events += self._set_status(DroneStatus.IDLE, ts, "Returned home")
                return events
            self.pos, _ = _move_towards(self.pos, t.home, max_step)
            return events

        # fallback
        events += self._complete_task(ts, "Unknown task")
        return events

    def _complete_task(self, ts: float, reason: str) -> List[DroneEvent]:
        tid = self.task.id if self.task else None
        self.task = None
        return [DroneEvent(
            type=DroneEventType.TASK_COMPLETED,
            drone_id=self.id,
            pos=self.pos,
            ts=ts,
            message=reason,
            status=self.status,
            task_id=tid
        )]
