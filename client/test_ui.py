from __future__ import annotations

import math
from typing import List

from ui import (
    PygameViewer, ViewerConfig,
    UIVec2, UIDroneState, UIZoneState, UIEvent, UIOverlay
)


def main():
    viewer = PygameViewer(ViewerConfig(world_w=100, world_h=100, title="UI Smoke Test (via ui/__init__.py)"))
    viewer.open()

    zones: List[UIZoneState] = [
        UIZoneState(id="z_fire", name="FireZone-A", type="FIRE_RISK", rect=(42, 58, 42, 58)),
        UIZoneState(id="z_nofly", name="NoFly", type="NO_FLY", rect=(10, 22, 60, 85)),
    ]

    perimeter = [
        UIVec2(40, 40),
        UIVec2(60, 40),
        UIVec2(60, 60),
        UIVec2(40, 60),
        UIVec2(40, 40),
    ]

    overlay = UIOverlay(
        polylines=[
            ("perimeter", perimeter, (255, 210, 120), 4),
            ("patrol", [UIVec2(10, 10), UIVec2(30, 30), UIVec2(70, 70), UIVec2(90, 90)], (70, 120, 190), 3),
        ],
        marker=("EVENT", UIVec2(50, 50), (255, 80, 80)),
        alert_lines=[
            "Type: FIRE",
            "Detected by: D1",
            "t = 12.0s",
            "conf=0.85  sev=0.90",
            "Perimeter margin: 4.0m",
        ],
    )

    ts = 0.0
    dt = 0.05
    step = 0

    while viewer.is_running():
        viewer.pump()
        viewer.tick()

        ts += dt
        step += 1

        drones: List[UIDroneState] = []
        for i, did in enumerate(["D1", "D2", "D3", "D4"]):
            x = 50 + 35 * math.cos(ts * (0.4 + 0.1 * i) + i)
            y = 50 + 35 * math.sin(ts * (0.55 + 0.07 * i) + 2 * i)
            status = "NAVIGATING" if i % 2 == 0 else "EXECUTING"
            battery = 100.0 - (ts * 0.2) % 30.0
            drones.append(UIDroneState(id=did, pos=UIVec2(x, y), status=status, battery=battery))

        events: List[UIEvent] = []
        if step % 120 == 0:
            events.append(UIEvent(ts=ts, level="INFO", title="HEARTBEAT", message="All drones nominal"))
        if step == 240:
            events.append(UIEvent(ts=ts, level="ALERT", title="FIRE_DETECTED", message="D1 reports fire in FireZone-A"))

        viewer.render(
            ts=ts,
            drones=drones,
            zones=zones,
            overlay=overlay,
            events=events,
            speed_hint=1.6,
        )

    viewer.close()


if __name__ == "__main__":
    main()
