from __future__ import annotations

from typing import Dict, List, Optional, Deque, Tuple
from collections import deque

import pygame

from drone import (
    Drone, DroneConfig, Vec2, DroneStatus,
    TaskType, PathTask, GoToTask
)
from world import (
    Map2D, Zone, ZoneType, Rect, ZoneEventPolicy, TriggerMode, WorldEventType
)

# ----------------- geometry helpers (strictly "around event area") -----------------

def rect_center(r: Rect) -> Vec2:
    return Vec2((r.xmin + r.xmax) / 2.0, (r.ymin + r.ymax) / 2.0)

def rect_perimeter_waypoints(r: Rect, margin: float = 0.0) -> List[Vec2]:
    """
    Return a closed-loop perimeter path (corners) around a rectangle, expanded by margin.
    Strictly follows the event boundary (expanded), NOT a circle.
    """
    xmin = r.xmin - margin
    xmax = r.xmax + margin
    ymin = r.ymin - margin
    ymax = r.ymax + margin
    return [
        Vec2(xmin, ymin),
        Vec2(xmax, ymin),
        Vec2(xmax, ymax),
        Vec2(xmin, ymax),
        Vec2(xmin, ymin),  # close
    ]

def polygon_center(poly: List[Vec2]) -> Vec2:
    if not poly:
        return Vec2(0.0, 0.0)
    sx = sum(p.x for p in poly)
    sy = sum(p.y for p in poly)
    return Vec2(sx / len(poly), sy / len(poly))

def expand_polygon_radially(poly: List[Vec2], margin: float) -> List[Vec2]:
    """
    Generic fallback for arbitrary polygon: push vertices away from centroid by (margin).
    This is NOT a true geometric offset, but it keeps the "around event shape" feel for demo.
    If you later add true arbitrary shapes, replace with a proper polygon offset algorithm.
    """
    if not poly:
        return poly
    c = polygon_center(poly)
    out: List[Vec2] = []
    for p in poly:
        v = p - c
        n = v.norm()
        if n < 1e-6:
            out.append(p)
        else:
            out.append(c + v * ((n + margin) / n))
    # close loop
    if out and (out[0].x != out[-1].x or out[0].y != out[-1].y):
        out.append(out[0])
    return out

def zone_perimeter_waypoints(z: Zone, margin: float) -> List[Vec2]:
    """
    Strictly "绕 event 的范围飞行"：
    - Rect: 用外扩后的矩形边界巡线
    - Polygon(如果你以后加了): 用外扩后的多边形顶点巡线（demo 近似）
    """
    if hasattr(z, "rect") and z.rect is not None:
        return rect_perimeter_waypoints(z.rect, margin=margin)
    # If you later implement non-rect zones, expose `z.polygon: List[Vec2]`
    if hasattr(z, "polygon") and z.polygon is not None:
        return expand_polygon_radially(list(z.polygon), margin=margin)
    # fallback: no shape info -> empty
    return []

# ----------------- rendering helpers -----------------

def v2_to_screen(p: Vec2, scale: float, ox: int, oy: int) -> Tuple[int, int]:
    return int(ox + p.x * scale), int(oy + p.y * scale)

def dist(a: Vec2, b: Vec2) -> float:
    return (a - b).norm()

def status_color(status: DroneStatus) -> Tuple[int, int, int]:
    if status == DroneStatus.IDLE:
        return (200, 200, 200)
    if status == DroneStatus.NAVIGATING:
        return (80, 160, 255)
    if status == DroneStatus.EXECUTING:
        return (255, 160, 80)
    if status == DroneStatus.RETURNING:
        return (180, 120, 255)
    if status == DroneStatus.OFFLINE:
        return (120, 120, 120)
    return (255, 80, 80)

def draw_text(surface, font, text, x, y, color=(240, 240, 245)):
    surface.blit(font.render(text, True, color), (x, y))

# ----------------- main -----------------

def main():
    pygame.init()
    pygame.display.set_caption("UAV Demo - Multi Patrol + Fire Perimeter Recon (2D)")

    world_w, world_h = 100, 100
    canvas_size = 820
    sidebar_w = 460
    win_w = canvas_size + sidebar_w
    win_h = canvas_size
    screen = pygame.display.set_mode((win_w, win_h))

    font = pygame.font.SysFont("Menlo", 16)
    font_small = pygame.font.SysFont("Menlo", 14)
    font_big = pygame.font.SysFont("Menlo", 20, bold=True)

    margin_px = 20
    scale = (canvas_size - 2 * margin_px) / world_w
    ox, oy = margin_px, margin_px

    # ---------- world ----------
    m = Map2D(world_w, world_h)
    m.set_seed(0)

    # Fire zone: rectangle event area (you can later replace with other shapes)
    fire_rect = Rect(42, 58, 42, 58)  # roughly centered at (50,50)
    fire_zone = Zone(
        id="z_fire",
        name="FireZone-A",
        type=ZoneType.FIRE_RISK,
        rect=fire_rect,
        policy=ZoneEventPolicy(
            trigger_mode=TriggerMode.ON_ENTER,
            probability=1.0,
            severity=0.9,
            confidence=0.85,
            cooldown_s=9999.0,  # (recommended: zones.py cooldown should apply to ON_ENTER too)
        )
    )
    m.add_zone(fire_zone)

    # ---------- drones ----------
    # ✅ slower speed (even slower than before)
    cfg = DroneConfig(
        speed_mps=1.6,          # <<<<<< slower
        battery_drain_per_s=0.02,
        heartbeat_period_s=1.0
    )

    drones: List[Drone] = [
        Drone(id="D1", pos=Vec2(10, 10), home=Vec2(10, 10), config=cfg),
        Drone(id="D2", pos=Vec2(90, 10), home=Vec2(90, 10), config=cfg),
        Drone(id="D3", pos=Vec2(10, 90), home=Vec2(10, 90), config=cfg),
        Drone(id="D4", pos=Vec2(90, 90), home=Vec2(90, 90), config=cfg),
    ]

    # ✅ four different patrol routes (all moving initially)
    # D1 route passes near/through fire zone to ensure trigger
    routes: Dict[str, List[Vec2]] = {
        "D1": [Vec2(10, 10), Vec2(30, 30), Vec2(49, 49), Vec2(70, 70), Vec2(90, 90)],
        "D2": [Vec2(90, 10), Vec2(70, 25), Vec2(60, 35), Vec2(70, 55), Vec2(90, 70), Vec2(90, 10)],
        "D3": [Vec2(10, 90), Vec2(25, 70), Vec2(35, 60), Vec2(55, 70), Vec2(70, 90), Vec2(10, 90)],
        "D4": [Vec2(90, 90), Vec2(70, 75), Vec2(60, 65), Vec2(75, 50), Vec2(90, 30), Vec2(90, 90)],
    }
    for d in drones:
        d.assign_task(PathTask(id=f"t_path_{d.id}", type=TaskType.PATH, waypoints=routes[d.id], loop=True), ts=0.0)

    # ---------- dispatch / recon plan ----------
    # strict perimeter recon around event area (not circle)
    PERIMETER_MARGIN = 4.0  # how far outside the event boundary to fly

    fire_event_zone: Optional[Zone] = None
    fire_center: Optional[Vec2] = None
    fire_perimeter: Optional[List[Vec2]] = None

    reinforcement_sent = False
    fire_first_report: Optional[dict] = None

    # For drones that are currently GOTO-ing to join recon perimeter:
    # when they arrive, switch them to PATH around perimeter.
    pending_recon_path: Dict[str, List[Vec2]] = {}

    # ---------- sim params ----------
    fps = 30
    dt = 0.2
    ts = 0.0

    # ---------- logs + trails ----------
    log: Deque[str] = deque(maxlen=30)
    def push_log(s: str):
        log.appendleft(s)
    push_log("Start: 4 drones patrolling on different routes...")

    trails: Dict[str, Deque[Vec2]] = {d.id: deque(maxlen=200) for d in drones}

    route_colors = {
        "D1": (70, 120, 190),
        "D2": (90, 190, 120),
        "D3": (190, 140, 90),
        "D4": (160, 100, 200),
    }

    clock = pygame.time.Clock()
    running = True

    while running:
        clock.tick(fps)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        ts += dt

        # ---- tick drones ----
        for d in drones:
            trails[d.id].append(d.pos)
            evs = d.tick(dt=dt, ts=ts, world_bounds=m.bounds())
            for e in evs:
                # keep logs readable
                if e.type in (e.type.STATUS_CHANGED, e.type.TASK_ASSIGNED):
                    push_log(f"[{ts:5.1f}] {e.drone_id} {e.type.name}: {e.message}")

        # ---- world events ----
        drone_positions: Dict[str, Vec2] = {d.id: d.pos for d in drones}
        wes = m.update_and_collect_events(drone_positions, ts)

        for we in wes:
            if we.type == WorldEventType.FIRE_DETECTED:
                push_log(f"[{ts:5.1f}] FIRE_DETECTED by {we.drone_id} @ ({we.pos.x:.1f},{we.pos.y:.1f})")

                if not reinforcement_sent:
                    reinforcement_sent = True

                    # lock the event zone (strictly recon around the zone's boundary)
                    fire_event_zone = fire_zone  # in this demo we know it’s FireZone-A
                    fire_center = rect_center(fire_event_zone.rect) if hasattr(fire_event_zone, "rect") else we.pos
                    fire_perimeter = zone_perimeter_waypoints(fire_event_zone, margin=PERIMETER_MARGIN)

                    fire_first_report = {
                        "ts": ts,
                        "drone_id": we.drone_id,
                        "pos": we.pos,
                        "severity": we.severity,
                        "confidence": we.confidence,
                        "zone": fire_event_zone.name if fire_event_zone else "FireZone",
                        "margin": PERIMETER_MARGIN
                    }

                    push_log(f"[{ts:5.1f}] DISPATCH: perimeter recon around EVENT boundary")

                    # spotter: switch immediately to perimeter PATH (not circle)
                    spotter = next(d for d in drones if d.id == we.drone_id)
                    if fire_perimeter and len(fire_perimeter) >= 2:
                        spotter.assign_task(PathTask(
                            id=f"t_recon_{spotter.id}",
                            type=TaskType.PATH,
                            waypoints=fire_perimeter,
                            loop=True
                        ), ts=ts)

                    # other 3: first GOTO to the nearest perimeter waypoint, then PATH loop
                    if fire_perimeter and len(fire_perimeter) >= 2:
                        for d in drones:
                            if d.id == spotter.id:
                                continue
                            # choose nearest perimeter waypoint as join point
                            join_wp = min(fire_perimeter[:-1], key=lambda p: dist(d.pos, p))
                            pending_recon_path[d.id] = fire_perimeter
                            d.assign_task(GoToTask(
                                id=f"t_join_{d.id}",
                                type=TaskType.GOTO,
                                target=join_wp,
                                arrive_eps=1.5
                            ), ts=ts)

        # ---- if a drone finished GOTO and has pending recon -> switch to perimeter PATH ----
        if reinforcement_sent and fire_perimeter:
            for d in drones:
                if d.id in pending_recon_path:
                    # In our drone implementation, GOTO completes -> task becomes None and status tends to IDLE
                    if d.task is None and d.status == DroneStatus.IDLE:
                        d.assign_task(PathTask(
                            id=f"t_recon_{d.id}",
                            type=TaskType.PATH,
                            waypoints=pending_recon_path[d.id],
                            loop=True
                        ), ts=ts)
                        push_log(f"[{ts:5.1f}] {d.id} joined perimeter recon")
                        del pending_recon_path[d.id]

        # ----------------- render -----------------
        screen.fill((18, 18, 20))

        # world border
        pygame.draw.rect(screen, (80, 80, 85), pygame.Rect(ox, oy, world_w * scale, world_h * scale), width=2)

        # zones
        zone_surface = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
        for z in m.zones:
            x1, y1 = v2_to_screen(Vec2(z.rect.xmin, z.rect.ymin), scale, ox, oy)
            x2, y2 = v2_to_screen(Vec2(z.rect.xmax, z.rect.ymax), scale, ox, oy)
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)

            if z.type == ZoneType.FIRE_RISK:
                color = (255, 80, 80, 70)
            else:
                color = (80, 255, 160, 50)

            pygame.draw.rect(zone_surface, color, pygame.Rect(rx, ry, rw, rh))
            draw_text(zone_surface, font_small, z.name, rx + 6, ry + 6, (235, 235, 240))
        screen.blit(zone_surface, (0, 0))

        # draw patrol routes
        for d in drones:
            wps = routes[d.id]
            pts = [v2_to_screen(p, scale, ox, oy) for p in wps]
            if len(pts) >= 2:
                pygame.draw.lines(screen, route_colors[d.id], False, pts, width=3)
            for i, p in enumerate(wps):
                sx, sy = v2_to_screen(p, scale, ox, oy)
                pygame.draw.circle(screen, route_colors[d.id], (sx, sy), 5)
                pygame.draw.circle(screen, (18, 18, 20), (sx, sy), 5, width=2)
                draw_text(screen, font_small, str(i), sx + 7, sy - 10, (210, 210, 220))

        # draw fire perimeter recon path (strictly around event boundary)
        if fire_perimeter and len(fire_perimeter) >= 2:
            pts = [v2_to_screen(p, scale, ox, oy) for p in fire_perimeter]
            pygame.draw.lines(screen, (255, 210, 120), False, pts, width=4)
            # highlight corners
            for p in fire_perimeter[:-1]:
                sx, sy = v2_to_screen(p, scale, ox, oy)
                pygame.draw.circle(screen, (255, 210, 120), (sx, sy), 6)
                pygame.draw.circle(screen, (18, 18, 20), (sx, sy), 6, width=2)

        # trails
        for d in drones:
            tr = trails[d.id]
            if len(tr) >= 2:
                pts_tr = [v2_to_screen(p, scale, ox, oy) for p in tr]
                pygame.draw.lines(screen, (60, 60, 70), False, pts_tr, width=2)

        # fire marker at zone center (for UI)
        if fire_center is not None:
            fx, fy = v2_to_screen(fire_center, scale, ox, oy)
            pygame.draw.circle(screen, (255, 80, 80), (fx, fy), 7)
            pygame.draw.circle(screen, (255, 80, 80), (fx, fy), 18, width=2)
            draw_text(screen, font_small, "EVENT", fx + 10, fy - 10, (255, 180, 180))

        # drones
        for d in drones:
            sx, sy = v2_to_screen(d.pos, scale, ox, oy)
            c = status_color(d.status)
            pygame.draw.circle(screen, c, (sx, sy), 8)
            pygame.draw.circle(screen, (15, 15, 16), (sx, sy), 8, width=2)
            draw_text(screen, font_small, f"{d.id}", sx + 10, sy - 10, (240, 240, 245))
            draw_text(screen, font_small, d.status.name, sx + 10, sy + 6, (200, 200, 210))

            # battery bar
            bx, by = sx + 10, sy + 24
            bw, bh = 62, 6
            pygame.draw.rect(screen, (60, 60, 65), pygame.Rect(bx, by, bw, bh))
            fill = int(bw * (d.battery / 100.0))
            pygame.draw.rect(screen, (120, 220, 120), pygame.Rect(bx, by, fill, bh))

        # sidebar
        sidebar_x = canvas_size
        pygame.draw.rect(screen, (25, 25, 28), pygame.Rect(sidebar_x, 0, sidebar_w, win_h))

        draw_text(screen, font_big, "UAV CONTROL", sidebar_x + 16, 14)
        draw_text(screen, font, f"Sim t={ts:6.1f}s  dt={dt:.1f}s  speed={cfg.speed_mps:.1f}m/s", sidebar_x + 16, 46, (210, 210, 215))

        # fire alert card
        card_y = 80
        card_h = 160
        pygame.draw.rect(screen, (32, 30, 30), pygame.Rect(sidebar_x + 16, card_y, sidebar_w - 32, card_h), border_radius=10)
        pygame.draw.rect(screen, (255, 80, 80), pygame.Rect(sidebar_x + 16, card_y, sidebar_w - 32, card_h), width=2, border_radius=10)
        draw_text(screen, font_big, "EVENT ALERT", sidebar_x + 28, card_y + 14, (255, 170, 170))

        if fire_first_report is None:
            draw_text(screen, font, "Status: none", sidebar_x + 28, card_y + 52, (220, 220, 225))
            draw_text(screen, font_small, "Patrolling... waiting for event", sidebar_x + 28, card_y + 78, (200, 200, 205))
            draw_text(screen, font_small, "On fire: all drones join PERIMETER path", sidebar_x + 28, card_y + 100, (200, 200, 205))
            draw_text(screen, font_small, "Recon path is drawn in yellow", sidebar_x + 28, card_y + 122, (200, 200, 205))
        else:
            draw_text(screen, font, f"Type: FIRE  zone={fire_first_report['zone']}", sidebar_x + 28, card_y + 52)
            draw_text(screen, font, f"Detected by: {fire_first_report['drone_id']}", sidebar_x + 28, card_y + 76)
            draw_text(screen, font, f"At t = {fire_first_report['ts']:.1f}s", sidebar_x + 28, card_y + 100)
            draw_text(screen, font, f"conf={fire_first_report['confidence']:.2f}  sev={fire_first_report['severity']:.2f}", sidebar_x + 28, card_y + 124)
            draw_text(screen, font, f"Perimeter margin: {fire_first_report['margin']:.1f}m", sidebar_x + 28, card_y + 148)

        # log
        draw_text(screen, font_big, "EVENT LOG", sidebar_x + 16, card_y + card_h + 18)
        y = card_y + card_h + 52
        for line in list(log)[:24]:
            draw_text(screen, font_small, line, sidebar_x + 16, y, (220, 220, 225))
            y += 18

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
