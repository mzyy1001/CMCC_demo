from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import uvicorn

# 用你已经写好的 edge_server（里面有 runtime / app）
import edge_server

# 用你抽象出来的 UI（通过 ui/__init__.py 暴露）
from ui import (
    PygameViewer, ViewerConfig,
    UIVec2, UIDroneState, UIZoneState, UIEvent, UIOverlay
)

# ----------------- helpers -----------------

def rect_to_perimeter(xmin: float, xmax: float, ymin: float, ymax: float, margin: float) -> List[UIVec2]:
    xmin -= margin
    xmax += margin
    ymin -= margin
    ymax += margin
    return [
        UIVec2(xmin, ymin),
        UIVec2(xmax, ymin),
        UIVec2(xmax, ymax),
        UIVec2(xmin, ymax),
        UIVec2(xmin, ymin),
    ]

def adapt_state_to_ui(state) -> Tuple[List[UIDroneState], List[UIZoneState]]:
    drones_ui: List[UIDroneState] = []
    for d in state.drones:
        drones_ui.append(
            UIDroneState(
                id=d.id,
                pos=UIVec2(d.pos.x, d.pos.y),
                status=d.status,
                battery=float(d.battery),
            )
        )

    zones_ui: List[UIZoneState] = []
    for z in state.zones:
        zones_ui.append(
            UIZoneState(
                id=z.id,
                name=z.name,
                type=z.type,
                rect=(z.rect.xmin, z.rect.xmax, z.rect.ymin, z.rect.ymax),
            )
        )
    return drones_ui, zones_ui

def pick_latest_fire_event(state) -> Optional[object]:
    # recent_events 是 EventModel 列表（pydantic model）
    for e in reversed(state.recent_events):
        if e.type == "FIRE_DETECTED":
            return e
    return None

def start_uvicorn_in_thread(host: str = "0.0.0.0", port: int = 8001):
    """
    在后台线程启动 uvicorn（pygame 在主线程更稳）。
    """
    config = uvicorn.Config(edge_server.app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t

# ----------------- main -----------------

def main():
    # 1) 启动 edge runtime（仿真 tick 线程）
    edge_server.runtime.start()

    # 2) 启动 http server（后台线程）
    server, t = start_uvicorn_in_thread(host="0.0.0.0", port=8001)

    # 3) 启动 viewer（主线程）
    viewer = PygameViewer(ViewerConfig(world_w=100, world_h=100, title="EDGE (UI + HTTP)"))
    viewer.open()

    # UI overlay config
    PERIMETER_MARGIN = 4.0

    # 让 UI log 里先提示一下怎么测
    viewer.push_log("Edge+UI started. Try curl POST /cmd/assign_task to move drones.")
    viewer.push_log("HTTP: http://localhost:8001/docs")

    try:
        while viewer.is_running():
            viewer.pump()
            viewer.tick()

            # 从 runtime 读状态（同一份仿真！）
            state = edge_server.runtime.get_state()
            drones_ui, zones_ui = adapt_state_to_ui(state)

            # Events -> UIEvent
            ui_events: List[UIEvent] = []
            # 只把最新的一两个事件刷到 log（避免每帧重复刷爆）
            # 简化：每次取最后 1 条
            if state.recent_events:
                last = state.recent_events[-1]
                ui_events.append(
                    UIEvent(
                        ts=float(last.ts),
                        level="ALERT" if last.type == "FIRE_DETECTED" else "INFO",
                        title=last.type,
                        message=(last.message or "")[:120],
                    )
                )

            # Overlay：如果有 fire event，就画“严格绕火区范围”的 perimeter
            overlay = UIOverlay(polylines=[])

            DRONE_COLORS = {
                "D1": (70, 120, 190),
                "D2": (120, 190, 70),
                "D3": (190, 70, 120),
                "D4": (190, 160, 70),
            }

            for d in state.drones:
                task = getattr(d, "task", None)
                if not task:
                    continue
                if getattr(task, "type", None) == "PATH":
                    wps = getattr(task, "waypoints", None) or []
                    pts = [UIVec2(p.x, p.y) for p in wps]
                    if len(pts) >= 2:
                        overlay.polylines.append(
                            (f"patrol:{d.id}", pts, DRONE_COLORS.get(d.id, (70, 120, 190)), 2)
                        )


            fire = pick_latest_fire_event(state)
            if fire is not None:
                # 找 fire zone（按名字或 type）
                fire_zone = None
                for z in zones_ui:
                    if z.type == "FIRE_RISK" or "FireZone" in z.name:
                        fire_zone = z
                        break

                if fire_zone is not None:
                    xmin, xmax, ymin, ymax = fire_zone.rect
                    perimeter = rect_to_perimeter(xmin, xmax, ymin, ymax, margin=PERIMETER_MARGIN)
                    overlay.polylines.append(("fire_perimeter", perimeter, (255, 210, 120), 4))

                    cx = (xmin + xmax) / 2.0
                    cy = (ymin + ymax) / 2.0
                    overlay.marker = ("EVENT", UIVec2(cx, cy), (255, 80, 80))

                    overlay.alert_lines = [
                        f"Type: {fire.type}",
                        f"By: {fire.drone_id}",
                        f"t = {fire.ts:.1f}s",
                        f"pos = ({fire.pos.x:.1f},{fire.pos.y:.1f})" if fire.pos else "pos = (n/a)",
                        f"margin = {PERIMETER_MARGIN:.1f}m",
                    ]

            viewer.render(
                ts=float(state.ts),
                drones=drones_ui,
                zones=zones_ui,
                overlay=overlay,
                events=ui_events,
                speed_hint=1.6,
            )

            # 给后台 server 一点呼吸（可选）
            time.sleep(0.001)

    finally:
        viewer.close()
        edge_server.runtime.stop()
        # uvicorn Server 没有特别优雅的 stop（demo 够用）
        # 关窗口即可退出进程


if __name__ == "__main__":
    main()
