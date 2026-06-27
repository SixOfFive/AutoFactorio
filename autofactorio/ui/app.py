"""Main application: window, input handling, and the per-frame update/draw loop.

Controls:
  mouse wheel        zoom in/out at the cursor
  right-drag / WASD / arrows   pan
  F                  follow the scout
  Space              pause / resume
  + / -              game speed
  I                  toggle detail panel
  L                  toggle comms console
  N                  force a director decision now
  F5 / F9            quicksave / quickload
  Esc                quit
"""

from __future__ import annotations

import os

import pygame

from .. import balance
from ..engine.simulation import Simulation
from ..ai.director import Director
from .assets import Assets
from .camera import Camera
from .renderer import Renderer
from .hud import Hud
from .console import Console
from .minimap import Minimap

HINT = ("wheel: zoom   right-drag/WASD: pan   click minimap: jump   F: follow scout   "
        "Space: pause   +/-: speed   I: details   L: comms   M: map   F5/F9: save/load   Esc: quit")

SAVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "saves", "quicksave.json")


class App:
    def __init__(self, config):
        self.config = config
        pygame.init()
        pygame.display.set_caption("AutoFactorio")
        flags = pygame.RESIZABLE | (pygame.FULLSCREEN if config.display.fullscreen else 0)
        self.screen = pygame.display.set_mode((config.display.width, config.display.height), flags)
        self.clock = pygame.time.Clock()

        self.assets = Assets()
        self.sim = Simulation(config)
        self.director = Director(self.sim, config)
        self.renderer = Renderer(self.assets)
        font = pygame.font.SysFont("consolas,couriernew,monospace", 16)
        small = pygame.font.SysFont("consolas,couriernew,monospace", 14)
        big = pygame.font.SysFont("consolas,couriernew,monospace", 22, bold=True)
        self.hud = Hud(font, small, big)
        self.console = Console(small, lines=8)
        self.minimap = Minimap()
        self.hint_font = small

        w, h = self.screen.get_size()
        self.cam = Camera(0, 0, 20.0, w, h)
        self.follow_scout = False
        self.follow_selected = False
        self.selected = None            # ('train', id) | ('field', id) | None
        self.show_console = True
        self.show_detail = False
        self.show_minimap = True
        self.running = True
        self.speed_idx = balance.GAME_SPEEDS.index(balance.DEFAULT_GAME_SPEED)

    # ---- loop -------------------------------------------------------------
    def run(self) -> None:
        try:
            while self.running:
                dt = self.clock.tick(self.config.display.fps) / 1000.0
                self._events()
                self._held_keys(dt)
                self._apply_follow()
                self.sim.tick(dt)
                self.director.update()
                self._draw()
                pygame.display.flip()
        finally:
            pygame.quit()

    # ---- input ------------------------------------------------------------
    def _events(self) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode((e.w, e.h), pygame.RESIZABLE)
                self.cam.resize(e.w, e.h)
            elif e.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                self.cam.zoom_at(mx, my, 1.12 ** e.y)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self.show_minimap and self.minimap.handle_click(e.pos, self.screen, self.cam, self.sim):
                    self.follow_scout = False
                    self.follow_selected = False
                else:
                    self._pick(e.pos)
            elif e.type == pygame.MOUSEMOTION:
                if e.buttons[2]:                       # right-button drag = grab pan
                    self.cam.pan_pixels(e.rel[0], e.rel[1])
                    self.follow_scout = False
            elif e.type == pygame.KEYDOWN:
                self._keydown(e)

    def _keydown(self, e) -> None:
        if e.key == pygame.K_ESCAPE:
            self.running = False
        elif e.key == pygame.K_SPACE:
            self.sim.paused = not self.sim.paused
        elif e.key == pygame.K_f:
            self.follow_scout = not self.follow_scout
            if self.follow_scout:
                self.follow_selected = False
        elif e.key == pygame.K_i:
            self.show_detail = not self.show_detail
        elif e.key == pygame.K_l:
            self.show_console = not self.show_console
        elif e.key == pygame.K_m:
            self.show_minimap = not self.show_minimap
        elif e.key == pygame.K_n:
            self.director.force_decision()
        elif e.key == pygame.K_F5:
            self.sim.save(SAVE_PATH)
        elif e.key == pygame.K_F9:
            if os.path.exists(SAVE_PATH):
                ok, _ = self.sim.load(SAVE_PATH)
                if ok:
                    self.director.reset()
            else:
                self.sim.log("No quicksave found (press F5 to save).")
        elif e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.speed_idx = min(self.speed_idx + 1, len(balance.GAME_SPEEDS) - 1)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]
        elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.speed_idx = max(self.speed_idx - 1, 0)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]

    def _pick(self, pos) -> None:
        """Select the nearest train (then field) to a world click; deselect on miss."""
        wx, wy = self.cam.screen_to_world(*pos)
        best = None
        best_d = 4.0 ** 2                     # within ~4 tiles of a loco
        for t in self.sim.trains.values():
            poses = t.car_poses()
            if not poses:
                continue
            d = (poses[0][0] - wx) ** 2 + (poses[0][1] - wy) ** 2
            if d < best_d:
                best_d, best = d, ("train", t.id)
        if best is not None:
            self.selected = best
            self.follow_selected = True
            self.follow_scout = False
            return
        for f in self.sim.fields.values():
            rad = (f.patch.radius + 3) ** 2
            if (f.patch.cx - wx) ** 2 + (f.patch.cy - wy) ** 2 < rad:
                self.selected = ("field", f.id)
                self.follow_selected = False
                self.cam.center_on(f.patch.cx, f.patch.cy)
                return
        self.selected = None
        self.follow_selected = False

    def _apply_follow(self) -> None:
        if self.follow_selected and self.selected and self.selected[0] == "train":
            t = self.sim.trains.get(self.selected[1])
            if t:
                poses = t.car_poses()
                if poses:
                    self.cam.center_on(poses[0][0], poses[0][1])
                    return
            self.follow_selected = False       # train gone (e.g. salvaged)
        if self.follow_scout:
            self.cam.center_on(*self.sim.scout.pos)

    def _held_keys(self, dt: float) -> None:
        k = pygame.key.get_pressed()
        pan = (700.0 * dt) / self.cam.zoom
        dx = dy = 0.0
        if k[pygame.K_a] or k[pygame.K_LEFT]:
            dx -= pan
        if k[pygame.K_d] or k[pygame.K_RIGHT]:
            dx += pan
        if k[pygame.K_w] or k[pygame.K_UP]:
            dy -= pan
        if k[pygame.K_s] or k[pygame.K_DOWN]:
            dy += pan
        if dx or dy:
            self.cam.pan_world(dx, dy)
            self.follow_scout = False

    # ---- draw -------------------------------------------------------------
    def _draw(self) -> None:
        self.renderer.draw(self.screen, self.cam, self.sim, self.selected)
        self.hud.draw(self.screen, self.sim, self.director, self.show_detail)
        if self.show_minimap:
            self.minimap.draw(self.screen, self.cam, self.sim)
        self._draw_selection_readout()
        if self.show_console:
            self.console.draw(self.screen, self.sim)
        else:
            hint = self.hint_font.render(HINT, True, (150, 156, 166))
            self.screen.blit(hint, (10, self.screen.get_height() - 22))

    def _draw_selection_readout(self) -> None:
        if not self.selected:
            return
        kind, sid = self.selected
        text = None
        if kind == "train":
            t = self.sim.trains.get(sid)
            if t:
                st = "following" if self.follow_selected else "selected"
                text = (f"Train #{sid} [{st}]  cargo {t.cargo_total()}/{t.capacity}  "
                        f"fuel {t.fuel_seconds:.0f}s  {t.state}"
                        + ("  STALLED" if t.stalled else ""))
        elif kind == "field":
            f = self.sim.fields.get(sid)
            if f:
                text = (f"Field #{sid}  {f.patch.ore}  drills {f.drills}  "
                        f"buffer {f.buffer}  reserve {int(f.patch.reserve)}")
        if not text:
            self.selected = None
            return
        surf = self.hint_font.render(text, True, (250, 240, 160))
        y = self.screen.get_height() - (self.console.lines * 18 + 16) - 22 if self.show_console \
            else self.screen.get_height() - 40
        bg = pygame.Surface((surf.get_width() + 12, 20), pygame.SRCALPHA)
        bg.fill((10, 12, 17, 200))
        self.screen.blit(bg, (8, y - 2))
        self.screen.blit(surf, (12, y))
