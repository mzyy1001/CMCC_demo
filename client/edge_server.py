from __future__ import annotations

import threading
import time
import random

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# 你的现有模块
from drone import (
    Drone, DroneConfig, Vec2, DroneStatus, TaskType, PathTask, GoToTask,
    FirefightingDrone, FirefightingConfig
)
from world import Map2D, Zone, ZoneType, Rect, ZoneEventPolicy, TriggerMode, WorldEventType


# -----------------------------
# Pydantic Schemas (HTTP I/O)
# -----------------------------

class Vec2Model(BaseModel):
    x: float
    y: float

class RectModel(BaseModel):
    xmin: float
    xmax: float
    ymin: float
    ymax: float

class AssignTaskRequest(BaseModel):
    drone_id: str
    task: Dict[str, Any]  # {"type":"GOTO", ...} / {"type":"PATH", ...} etc.

class BatchAssignRequest(BaseModel):
    commands: List[AssignTaskRequest]

class DroneStateModel(BaseModel):
    id: str
    pos: Vec2Model
    status: str
    battery: float
    task: Optional[Dict[str, Any]] = None

class ZoneStateModel(BaseModel):
    id: str
    name: str
    type: str
    rect: RectModel

class EventModel(BaseModel):
    ts: float
    type: str
    drone_id: Optional[str] = None
    pos: Optional[Vec2Model] = None
    message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    severity: Optional[float] = None
    confidence: Optional[float] = None

class StateResponse(BaseModel):
    ts: float
    drones: List[DroneStateModel]
    zones: List[ZoneStateModel]
    recent_events: List[EventModel]


# -----------------------------
# Runtime (thread-safe sim)
# -----------------------------

class EdgeRuntime:
    """
    管理端侧仿真：
    - 背景线程 tick: drones + world
    - HTTP 线程下发任务：thread-safe
    """
    def __init__(self, world_w: int = 100, world_h: int = 100, dt: float = 0.2):
        self.dt = dt
        self.ts = 0.0

        self.lock = threading.RLock()
        self.events: Deque[EventModel] = deque(maxlen=200)

        # world
        self.world = Map2D(world_w, world_h)
        self.world.set_seed(0)

        rng = random.Random(time.time())   # 每次启动随机；想复现就换成固定 seed(int)

        FIRE_N_MIN, FIRE_N_MAX = 2, 3
        FIRE_SIZE_MIN, FIRE_SIZE_MAX = 6.0, 12.0   # 火场更小：边长范围 6~12
        BORDER = 8.0                               # 离地图边缘留点距离，避免贴边

        n_fire = rng.randint(FIRE_N_MIN, FIRE_N_MAX)
        self.fire_zones: List[Zone] = []

        for i in range(n_fire):
            w = rng.uniform(FIRE_SIZE_MIN, FIRE_SIZE_MAX)
            h = rng.uniform(FIRE_SIZE_MIN, FIRE_SIZE_MAX)

            xmin = rng.uniform(BORDER, world_w - BORDER - w)
            ymin = rng.uniform(BORDER, world_h - BORDER - h)
            xmax = xmin + w
            ymax = ymin + h

            fire_rect = Rect(xmin, xmax, ymin, ymax)

            z = Zone(
                id=f"z_fire_{i+1}",
                name=f"FireZone-{i+1}",
                type=ZoneType.FIRE_RISK,
                rect=fire_rect,
                policy=ZoneEventPolicy(
                    trigger_mode=TriggerMode.ON_ENTER,
                    probability=1.0,
                    severity=float(rng.uniform(0.75, 0.95)),
                    confidence=float(rng.uniform(0.75, 0.95)),
                    cooldown_s=9999.0,
                ),
            )

            self.world.add_zone(z)
            self.fire_zones.append(z)

        # drones
        cfg = DroneConfig(speed_mps=1.6, battery_drain_per_s=0.02, heartbeat_period_s=1.0)

        MARGIN = 5.0
        corners = {
            "D1": Vec2(MARGIN, MARGIN),                         # bottom-left
            "D2": Vec2(world_w - MARGIN, MARGIN),               # bottom-right
            "D3": Vec2(MARGIN, world_h - MARGIN),               # top-left
            "D4": Vec2(world_w - MARGIN, world_h - MARGIN),     # top-right
        }

        self.drones: Dict[str, Drone] = {
            did: Drone(
                id=did,
                pos=pos,
                home=Vec2(pos.x, pos.y),
                config=cfg,
            )
            for did, pos in corners.items()
        }

        ff_cfg = FirefightingConfig(
            speed_mps=1.8,
            battery_drain_per_s=0.03,
            heartbeat_period_s=1.0,
            agent_capacity=80.0,
            agent_use_per_s=1.5,
            suppress_range_m=6.0,
            refill_at_home=True,
        )

        dock_y = MARGIN
        dock_x0 = world_w * 0.5 - 6.0

        fire_docks = {
            "FD1": Vec2(dock_x0 + 0.0, dock_y),
            "FD2": Vec2(dock_x0 + 4.0, dock_y),
            "FD3": Vec2(dock_x0 + 8.0, dock_y),
            "FD4": Vec2(dock_x0 + 12.0, dock_y),
        }

        for did, pos in fire_docks.items():
            self.drones[did] = FirefightingDrone(
                id=did,
                pos=pos,
                home=Vec2(pos.x, pos.y),
                config=ff_cfg,
            )


        # default patrol routes (端侧启动就让它们先巡逻，云侧再接管也行)
        # routes: Dict[str, List[Vec2]] = {
        #     "D1": [Vec2(10, 10), Vec2(30, 30), Vec2(49, 49), Vec2(70, 70), Vec2(90, 90)],
        #     "D2": [Vec2(90, 10), Vec2(70, 25), Vec2(60, 35), Vec2(70, 55), Vec2(90, 70), Vec2(90, 10)],
        #     "D3": [Vec2(10, 90), Vec2(25, 70), Vec2(35, 60), Vec2(55, 70), Vec2(70, 90), Vec2(10, 90)],
        #     "D4": [Vec2(90, 90), Vec2(70, 75), Vec2(60, 65), Vec2(75, 50), Vec2(90, 30), Vec2(90, 90)],
        # }
        # for did, d in self.drones.items():
        #     d.assign_task(PathTask(id=f"t_patrol_{did}", type=TaskType.PATH, waypoints=routes[did], loop=True), ts=0.0)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        # fixed-step loop (simulation time)
        while not self._stop.is_set():
            t0 = time.time()
            with self.lock:
                self.ts += self.dt

                # tick drones
                for d in self.drones.values():
                    d.tick(dt=self.dt, ts=self.ts, world_bounds=self.world.bounds())

                # world events
                positions = {did: d.pos for did, d in self.drones.items()}
                wes = self.world.update_and_collect_events(positions, self.ts)

                for we in wes:
                    ev = EventModel(
                        ts=self.ts,
                        type=we.type.name,
                        drone_id=getattr(we, "drone_id", None),
                        pos=Vec2Model(x=we.pos.x, y=we.pos.y) if getattr(we, "pos", None) is not None else None,
                        message=getattr(we, "message", None),
                        payload=getattr(we, "payload", None),
                        severity=getattr(we, "severity", None),
                        confidence=getattr(we, "confidence", None),
                    )
                    self.events.append(ev)

            # real-time pacing (so it doesn't run at max speed)
            elapsed = time.time() - t0
            sleep_s = max(0.0, self.dt - elapsed)
            time.sleep(sleep_s)

    # ----- API helpers -----

    def get_state(self) -> StateResponse:
        with self.lock:
            drones_out: List[DroneStateModel] = []
            for d in self.drones.values():
                drones_out.append(
                    DroneStateModel(
                        id=d.id,
                        pos=Vec2Model(x=d.pos.x, y=d.pos.y),
                        status=d.status.name,
                        battery=float(d.battery),
                        task=self._task_to_dict(d),
                    )
                )

            zones_out: List[ZoneStateModel] = []
            for z in self.world.zones:
                zones_out.append(
                    ZoneStateModel(
                        id=z.id,
                        name=z.name,
                        type=z.type.name,
                        rect=RectModel(xmin=z.rect.xmin, xmax=z.rect.xmax, ymin=z.rect.ymin, ymax=z.rect.ymax),
                    )
                )

            return StateResponse(
                ts=self.ts,
                drones=drones_out,
                zones=zones_out,
                recent_events=list(self.events)[-50:],
            )

    def assign_task(self, drone_id: str, task_payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if drone_id not in self.drones:
                raise ValueError(f"Unknown drone_id={drone_id}")
            d = self.drones[drone_id]
            task = self._parse_task(task_payload)
            d.assign_task(task, ts=self.ts)
            return {"ok": True, "drone_id": drone_id, "assigned": task_payload}

    def batch_assign(self, cmds: List[AssignTaskRequest]) -> Dict[str, Any]:
        results = []
        for c in cmds:
            try:
                results.append(self.assign_task(c.drone_id, c.task))
            except Exception as e:
                results.append({"ok": False, "drone_id": c.drone_id, "error": str(e)})
        return {"ok": True, "results": results}

    # ----- task parsing -----

    def _parse_task(self, p: Dict[str, Any]):
        """
        端侧统一接受 JSON task：
          {"type":"GOTO","target":{"x":..,"y":..},"arrive_eps":2.0}
          {"type":"PATH","waypoints":[{"x":..,"y":..},...],"loop":true}
        你之后要加更多 task，只在这里扩展。
        """
        t = (p.get("type") or "").upper()

        if t == "GOTO":
            tgt = p["target"]
            arrive_eps = float(p.get("arrive_eps", 2.0))
            return GoToTask(
                id=p.get("id", f"goto_{int(self.ts*10)}"),
                type=TaskType.GOTO,
                target=Vec2(float(tgt["x"]), float(tgt["y"])),
                arrive_eps=arrive_eps,
            )

        if t == "PATH":
            wps = p["waypoints"]
            loop = bool(p.get("loop", True))
            pts = [Vec2(float(w["x"]), float(w["y"])) for w in wps]
            return PathTask(
                id=p.get("id", f"path_{int(self.ts*10)}"),
                type=TaskType.PATH,
                waypoints=pts,
                loop=loop,
            )

        if t == "HOLD":
            # simplest hold: a 2-point path with loop (or you can add a HoldTask later)
            pos = self.drones[p["drone_id"]].pos if "drone_id" in p else None
            if pos is None:
                raise ValueError("HOLD requires drone_id in payload or add a real HoldTask")
            pts = [pos, pos]
            return PathTask(id=p.get("id", f"hold_{int(self.ts*10)}"), type=TaskType.PATH, waypoints=pts, loop=True)

        raise ValueError(f"Unsupported task type: {t}")

    def _task_to_dict(self, d: Drone) -> Optional[Dict[str, Any]]:
        # best-effort serialization for debugging/state
        if d.task is None:
            return None
        td: Dict[str, Any] = {"type": getattr(d.task, "type", None).name if getattr(d.task, "type", None) else str(type(d.task))}
        if isinstance(d.task, GoToTask):
            td["target"] = {"x": d.task.target.x, "y": d.task.target.y}
            td["arrive_eps"] = d.task.arrive_eps
        if isinstance(d.task, PathTask):
            td["waypoints"] = [{"x": p.x, "y": p.y} for p in d.task.waypoints]
            td["loop"] = d.task.loop
        return td


# -----------------------------
# FastAPI app
# -----------------------------

runtime = EdgeRuntime()
app = FastAPI(title="Edge UAV API", version="0.1")

@app.on_event("startup")
def _startup():
    runtime.start()

@app.on_event("shutdown")
def _shutdown():
    runtime.stop()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/state", response_model=StateResponse)
def get_state():
    return runtime.get_state()

@app.post("/cmd/assign_task")
def assign_task(req: AssignTaskRequest):
    try:
        return runtime.assign_task(req.drone_id, req.task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/cmd/batch")
def batch(req: BatchAssignRequest):
    return runtime.batch_assign(req.commands)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)


