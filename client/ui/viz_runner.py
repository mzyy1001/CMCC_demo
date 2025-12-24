from __future__ import annotations

from typing import Dict, List, Optional

from ui.pygame_viewer import PygameViewer, ViewerConfig
from ui.types import UIVec2, UIDroneState, UIZoneState, UIEvent, UIOverlay

from drone import Drone, DroneConfig, Vec2, DroneStatus, TaskType, PathTask, GoToTask
from world import Map2D, Zone, ZoneType, Rect, ZoneEventPolicy, TriggerMode, WorldEventType


# ---------- adapters (domain -> UI) ----------

def adapt_drones(drones: List[Drone]) -> List[UIDroneState]:
    out: List[UIDroneState] = []
    for d in drones:
        out.append(UIDroneState(
            id=d.id,
            pos=UIVec2(d.pos.x, d.pos.y),
            status=d.status.name,
            battery=float(d.battery),
        ))
    return out

def adapt_zones(zones: List[Zone]) -> List[UIZoneState]:
    out: List[UIZoneState] = []
    for z in zones:
        out.append(UIZoneState(
            id=z.id,
            name=z.name,
            type=z.type.name,
            rect=(z.rect.xmin, z.rect.xmax, z.rect.ymin, z.rect.ymax),
        ))
    return out


# ---------- "brain" placeholder ----------
# 你未来替换成 LLM brain：输入 events + states -> 输出 tasks/commands
class RuleBrain:
    def __init__(self):
        self.dispatched = False
        self.fire_perimeter: Optional[List[Vec2]] = None
        self.fire_zone: Optional[Zone] = None

    def step(self, ts: float, drones: List[Drone], world_events) -> Dict:
        """
        return: dict with
          - "ui_events": List[UIEvent]
          - "overlay": UIOverlay
        """
        ui_events: List[UIEvent] = []
        overlay = UIOverlay(polylines=[])

        for we in world_events:
            if we.type == WorldEventType.FIRE_DETECTED and not self.dispatched:
                self.dispatched = True
                self.fire_zone = None
                # 这里演示：找到触发 zone（你也可以从 we.payload 里带 zone_id）
                # demo 里只有一个 fire zone
                # 你可以把 fire zone 作为参数传进 brain
                ui_events.append(UIEvent(ts=ts, level="ALERT", title="FIRE_DETECTED",
                                         message=f"by {we.drone_id} @ ({we.pos.x:.1f},{we.pos.y:.1f})"))

                # perimeter path（strictly around rect）
                z = we.payload.get("zone_obj") if (we.payload and "zone_obj" in we.payload) else None
                if z is None:
                    # fallback: no zone object, skip overlay path
                    pass
                else:
                    self.fire_zone = z

                # 调度：让所有机 join perimeter（这里只是示意；你在 main 里可做）
        # overlay 你可以在 main 里根据 brain 的内部状态生成
        return {"ui_events": ui_events, "overlay": overlay}


def main():
    # --- setup world & drones ---
    world_w, world_h = 100, 100
    m = Map2D(world_w, world_h)
    m.set_seed(0)

    fire_rect = Rect(42, 58, 42, 58)
    fire_zone = Zone(
        id="z_fire",
        name="FireZone-A",
        type=ZoneType.FIRE_RISK,
        rect=fire_rect,
        policy=ZoneEventPolicy(trigger_mode=TriggerMode.ON_ENTER, probability=1.0, severity=0.9, confidence=0.85, cooldown_s=9999.0)
    )
    m.add_zone(fire_zone)

    cfg = DroneConfig(speed_mps=1.6, battery_drain_per_s=0.02, heartbeat_period_s=1.0)
    drones = [
        Drone(id="D1", pos=Vec2(10, 10), home=Vec2(10, 10), config=cfg),
        Drone(id="D2", pos=Vec2(90, 10), home=Vec2(90, 10), config=cfg),
        Drone(id="D3", pos=Vec2(10, 90), home=Vec2(10, 90), config=cfg),
        Drone(id="D4", pos=Vec2(90, 90), home=Vec2(90, 90), config=cfg),
    ]

    routes = {
        "D1": [Vec2(10, 10), Vec2(30, 30), Vec2(49, 49), Vec2(70, 70), Vec2(90, 90)],
        "D2": [Vec2(90, 10), Vec2(70, 25), Vec2(60, 35), Vec2(70, 55), Vec2(90, 70), Vec2(90, 10)],
        "D3": [Vec2(10, 90), Vec2(25, 70), Vec2(35, 60), Vec2(55, 70), Vec2(70, 90), Vec2(10, 90)],
        "D4": [Vec2(90, 90), Vec2(70, 75), Vec2(60, 65), Vec2(75, 50), Vec2(90, 30), Vec2(90, 90)],
    }
    for d in drones:
        d.assign_task(PathTask(id=f"t_path_{d.id}", type=TaskType.PATH, waypoints=routes[d.id], loop=True), ts=0.0)

    # --- viewer ---
    viewer = PygameViewer(ViewerConfig(world_w=world_w, world_h=world_h, title="UAV Viewer (plug-in brain ready)"))
    viewer.open()

    # --- brain (replace later) ---
    brain = RuleBrain()

    # --- sim loop ---
    fps = viewer.cfg.fps
    dt = 0.2
    ts = 0.0

    # Example overlay: draw the 4 patrol routes always
    patrol_overlay = UIOverlay(polylines=[])
    colors = {"D1": (70, 120, 190), "D2": (90, 190, 120), "D3": (190, 140, 90), "D4": (160, 100, 200)}
    for did, wps in routes.items():
        patrol_overlay.polylines.append((f"route_{did}", [UIVec2(p.x, p.y) for p in wps], colors[did], 3))

    while viewer.is_running():
        viewer.pump()
        viewer.tick()

        ts += dt

        # tick drones
        for d in drones:
            d.tick(dt=dt, ts=ts, world_bounds=m.bounds())

        # world events
        drone_positions = {d.id: d.pos for d in drones}
        world_events = m.update_and_collect_events(drone_positions, ts)

        # ---- your brain hook point ----
        # 你未来在这里：把 (drones state + world_events) 变成指令，调用 d.assign_task(...)
        # 这里先用 RuleBrain 占位（不做调度）
        brain_out = brain.step(ts, drones, world_events)
        ui_events: List[UIEvent] = brain_out.get("ui_events", [])
        overlay: UIOverlay = brain_out.get("overlay", UIOverlay(polylines=[]))

        # Combine overlays: patrol routes + brain overlay
        merged = UIOverlay(
            polylines=list(patrol_overlay.polylines) + list(overlay.polylines),
            marker=overlay.marker,
            alert_lines=overlay.alert_lines,
        )

        # render
        viewer.render(
            ts=ts,
            drones=adapt_drones(drones),
            zones=adapt_zones(m.zones),
            overlay=merged,
            events=ui_events,
            speed_hint=cfg.speed_mps,
        )

    viewer.close()


if __name__ == "__main__":
    main()
