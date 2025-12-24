from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import pygame

from .types import UIVec2, UIDroneState, UIZoneState, UIEvent, UIOverlay


def v2_to_screen(p: UIVec2, scale: float, ox: int, oy: int) -> Tuple[int, int]:
    return int(ox + p.x * scale), int(oy + p.y * scale)


def default_status_color(status: str) -> Tuple[int, int, int]:
    if status == "IDLE":
        return (200, 200, 200)
    if status == "NAVIGATING":
        return (80, 160, 255)
    if status == "EXECUTING":
        return (255, 160, 80)
    if status == "RETURNING":
        return (180, 120, 255)
    if status == "OFFLINE":
        return (120, 120, 120)
    return (255, 80, 80)


@dataclass
class ViewerConfig:
    world_w: int = 100
    world_h: int = 100
    canvas_size: int = 820
    sidebar_w: int = 460
    margin_px: int = 20
    fps: int = 30
    title: str = "UAV Viewer"


class PygameViewer:
    """
    可复用 UI：只负责“画”，不负责“算 / 调度 / 更新仿真”。
    你每一帧调用 render(...) 传入状态即可。

    使用方式：
      viewer = PygameViewer(ViewerConfig(...))
      viewer.open()
      while viewer.is_running():
          viewer.pump()  # 处理窗口事件
          viewer.render(ts, drones, zones, overlay=..., events=...)
          viewer.tick()  # 控 FPS
    """

    def __init__(self, cfg: ViewerConfig):
        self.cfg = cfg
        self.running = False

        self.scale = None
        self.ox = None
        self.oy = None

        self.screen = None
        self.clock = None

        self.font = None
        self.font_small = None
        self.font_big = None

        self.log: Deque[str] = deque(maxlen=30)
        self.trails: Dict[str, Deque[UIVec2]] = {}

    def open(self):
        pygame.init()
        pygame.display.set_caption(self.cfg.title)

        win_w = self.cfg.canvas_size + self.cfg.sidebar_w
        win_h = self.cfg.canvas_size
        self.screen = pygame.display.set_mode((win_w, win_h))

        self.font = pygame.font.SysFont("Menlo", 16)
        self.font_small = pygame.font.SysFont("Menlo", 14)
        self.font_big = pygame.font.SysFont("Menlo", 20, bold=True)

        self.clock = pygame.time.Clock()

        self.scale = (self.cfg.canvas_size - 2 * self.cfg.margin_px) / self.cfg.world_w
        self.ox = self.cfg.margin_px
        self.oy = self.cfg.margin_px

        self.running = True
        self.log.appendleft("Viewer started.")

    def is_running(self) -> bool:
        return self.running

    def close(self):
        self.running = False
        pygame.quit()

    def pump(self):
        # Handle window events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

    def tick(self):
        self.clock.tick(self.cfg.fps)

    def push_log(self, line: str):
        self.log.appendleft(line)

    def _draw_text(self, text: str, x: int, y: int, color=(240, 240, 245), small=False, big=False):
        font = self.font_small if small else self.font_big if big else self.font
        self.screen.blit(font.render(text, True, color), (x, y))

    def render(
        self,
        ts: float,
        drones: List[UIDroneState],
        zones: List[UIZoneState],
        overlay: Optional[UIOverlay] = None,
        events: Optional[List[UIEvent]] = None,
        speed_hint: Optional[float] = None,
    ):
        if not self.running:
            return

        # update trails
        for d in drones:
            if d.id not in self.trails:
                self.trails[d.id] = deque(maxlen=220)
            self.trails[d.id].append(d.pos)

        # add events to log
        if events:
            for e in events:
                prefix = {"INFO": "i", "WARN": "!", "ALERT": "!!"}.get(e.level, "i")
                self.log.appendleft(f"[{e.ts:5.1f}] {prefix} {e.title}: {e.message}")

        # background
        self.screen.fill((18, 18, 20))

        # world border
        pygame.draw.rect(
            self.screen,
            (80, 80, 85),
            pygame.Rect(self.ox, self.oy, self.cfg.world_w * self.scale, self.cfg.world_h * self.scale),
            width=2,
        )

        # zones
        zone_surface = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        for z in zones:
            xmin, xmax, ymin, ymax = z.rect
            x1, y1 = v2_to_screen(UIVec2(xmin, ymin), self.scale, self.ox, self.oy)
            x2, y2 = v2_to_screen(UIVec2(xmax, ymax), self.scale, self.ox, self.oy)
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)

            if z.type == "FIRE_RISK":
                color = (255, 80, 80, 70)
            elif z.type == "NO_FLY":
                color = (180, 80, 255, 70)
            elif z.type == "SIGNAL_LOSS":
                color = (255, 220, 80, 70)
            else:
                color = (80, 255, 160, 50)

            pygame.draw.rect(zone_surface, color, pygame.Rect(rx, ry, rw, rh))
            # label
            label = self.font_small.render(z.name, True, (235, 235, 240))
            zone_surface.blit(label, (rx + 6, ry + 6))

        self.screen.blit(zone_surface, (0, 0))

        # overlay: polylines & marker
        if overlay:
            for name, pts, color, width in overlay.polylines:
                if pts and len(pts) >= 2:
                    spts = [v2_to_screen(p, self.scale, self.ox, self.oy) for p in pts]
                    pygame.draw.lines(self.screen, color, False, spts, width=width)
            if overlay.marker:
                label, p, color = overlay.marker
                sx, sy = v2_to_screen(p, self.scale, self.ox, self.oy)
                pygame.draw.circle(self.screen, color, (sx, sy), 7)
                pygame.draw.circle(self.screen, color, (sx, sy), 18, width=2)
                self._draw_text(label, sx + 10, sy - 10, color=(255, 220, 220), small=True)

        # trails
        for d in drones:
            tr = self.trails.get(d.id)
            if tr and len(tr) >= 2:
                pts_tr = [v2_to_screen(p, self.scale, self.ox, self.oy) for p in tr]
                pygame.draw.lines(self.screen, (60, 60, 70), False, pts_tr, width=2)

        # drones
        for d in drones:
            sx, sy = v2_to_screen(d.pos, self.scale, self.ox, self.oy)
            c = default_status_color(d.status)
            pygame.draw.circle(self.screen, c, (sx, sy), 8)
            pygame.draw.circle(self.screen, (15, 15, 16), (sx, sy), 8, width=2)

            self._draw_text(d.id, sx + 10, sy - 10, small=True)
            self._draw_text(d.status, sx + 10, sy + 6, color=(200, 200, 210), small=True)

            # battery
            bx, by = sx + 10, sy + 24
            bw, bh = 62, 6
            pygame.draw.rect(self.screen, (60, 60, 65), pygame.Rect(bx, by, bw, bh))
            fill = int(bw * max(0.0, min(1.0, d.battery / 100.0)))
            pygame.draw.rect(self.screen, (120, 220, 120), pygame.Rect(bx, by, fill, bh))

        # sidebar
        sidebar_x = self.cfg.canvas_size
        pygame.draw.rect(self.screen, (25, 25, 28), pygame.Rect(sidebar_x, 0, self.cfg.sidebar_w, self.cfg.canvas_size))

        self._draw_text("UAV CONTROL", sidebar_x + 16, 14, big=True)
        hint = f"Sim t={ts:6.1f}s"
        if speed_hint is not None:
            hint += f"  speed={speed_hint:.1f}m/s"
        self._draw_text(hint, sidebar_x + 16, 46, color=(210, 210, 215))

        # alert card
        card_y = 80
        card_h = 170
        pygame.draw.rect(self.screen, (32, 30, 30), pygame.Rect(sidebar_x + 16, card_y, self.cfg.sidebar_w - 32, card_h), border_radius=10)
        pygame.draw.rect(self.screen, (255, 80, 80), pygame.Rect(sidebar_x + 16, card_y, self.cfg.sidebar_w - 32, card_h), width=2, border_radius=10)
        self._draw_text("ALERT", sidebar_x + 28, card_y + 14, color=(255, 170, 170), big=True)

        if overlay and overlay.alert_lines:
            y = card_y + 52
            for line in overlay.alert_lines[:6]:
                self._draw_text(line, sidebar_x + 28, y, small=True)
                y += 22
        else:
            self._draw_text("Status: none", sidebar_x + 28, card_y + 52, color=(220, 220, 225))
            self._draw_text("Waiting for events...", sidebar_x + 28, card_y + 78, color=(200, 200, 205), small=True)

        # log
        self._draw_text("EVENT LOG", sidebar_x + 16, card_y + card_h + 18, big=True)
        y = card_y + card_h + 52
        for line in list(self.log)[:24]:
            self._draw_text(line, sidebar_x + 16, y, color=(220, 220, 225), small=True)
            y += 18

        pygame.display.flip()
