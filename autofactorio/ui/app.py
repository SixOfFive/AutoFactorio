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
  Esc                quit
"""

from __future__ import annotations

import pygame

from .. import balance
from ..engine.simulation import Simulation
from ..ai.director import Director
from .assets import Assets
from .camera import Camera
from .renderer import Renderer
from .hud import Hud
from .console import Console

HINT = ("wheel: zoom   right-drag/WASD: pan   F: follow scout   Space: pause   "
        "+/-: speed   I: details   L: comms   Esc: quit")


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
        self.hint_font = small

        w, h = self.screen.get_size()
        self.cam = Camera(0, 0, 20.0, w, h)
        self.follow_scout = False
        self.show_console = True
        self.show_detail = False
        self.running = True
        self.speed_idx = balance.GAME_SPEEDS.index(balance.DEFAULT_GAME_SPEED)

    # ---- loop -------------------------------------------------------------
    def run(self) -> None:
        try:
            while self.running:
                dt = self.clock.tick(self.config.display.fps) / 1000.0
                self._events()
                self._held_keys(dt)
                if self.follow_scout:
                    self.cam.center_on(*self.sim.scout.pos)
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
        elif e.key == pygame.K_i:
            self.show_detail = not self.show_detail
        elif e.key == pygame.K_l:
            self.show_console = not self.show_console
        elif e.key == pygame.K_n:
            self.director.force_decision()
        elif e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.speed_idx = min(self.speed_idx + 1, len(balance.GAME_SPEEDS) - 1)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]
        elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.speed_idx = max(self.speed_idx - 1, 0)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]

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
        self.renderer.draw(self.screen, self.cam, self.sim)
        self.hud.draw(self.screen, self.sim, self.director, self.show_detail)
        if self.show_console:
            self.console.draw(self.screen, self.sim)
        else:
            hint = self.hint_font.render(HINT, True, (150, 156, 166))
            self.screen.blit(hint, (10, self.screen.get_height() - 22))
