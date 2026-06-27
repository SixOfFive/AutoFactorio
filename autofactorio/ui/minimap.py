"""Corner minimap: whole-map overview of fog, patches, fields, trains, scout,
and the current camera viewport. Click it to jump the camera there.
"""

from __future__ import annotations

import numpy as np
import pygame

ORE_COLORS = {
    "iron_ore": (120, 140, 162),
    "copper_ore": (205, 120, 66),
    "coal": (54, 54, 64),
    "stone": (180, 166, 134),
}


class Minimap:
    def __init__(self, size: int = 210):
        self.size = size
        self._base: pygame.Surface | None = None
        self._tick = 0

    def rect(self, screen) -> pygame.Rect:
        return pygame.Rect(screen.get_width() - self.size - 12, 72, self.size, self.size)

    # ---- transforms -------------------------------------------------------
    def _w2m(self, world, wx, wy, rect):
        span = world.size
        fx = (wx + world.radius) / span
        fy = (wy + world.radius) / span
        return rect.x + fx * rect.w, rect.y + fy * rect.h

    def _m2w(self, world, px, py, rect):
        span = world.size
        wx = (px - rect.x) / rect.w * span - world.radius
        wy = (py - rect.y) / rect.h * span - world.radius
        return wx, wy

    # ---- base fog/terrain surface (rebuilt periodically) ------------------
    def _rebuild_base(self, world):
        s = world.size
        arr = np.zeros((s, s, 3), dtype=np.uint8)
        arr[world.explored == 1] = (44, 74, 46)
        surf = pygame.surfarray.make_surface(np.transpose(arr, (1, 0, 2)))
        self._base = pygame.transform.scale(surf, (self.size, self.size))

    # ---- draw -------------------------------------------------------------
    def draw(self, screen, cam, sim):
        rect = self.rect(screen)
        self._tick += 1
        if self._base is None or self._tick % 20 == 0:
            self._rebuild_base(sim.world)
        world = sim.world
        pygame.draw.rect(screen, (10, 12, 17), rect.inflate(8, 8))
        screen.blit(self._base, rect.topleft)

        for p in world.patches:
            if not p.discovered:
                continue
            x, y = self._w2m(world, p.cx, p.cy, rect)
            col = (95, 95, 100) if p.depleted else ORE_COLORS.get(p.ore, (200, 200, 200))
            pygame.draw.circle(screen, col, (int(x), int(y)), 2)

        for f in sim.fields.values():
            x, y = self._w2m(world, f.patch.cx, f.patch.cy, rect)
            pygame.draw.rect(screen, (236, 238, 246), (int(x) - 2, int(y) - 2, 4, 4))

        for t in sim.trains.values():
            poses = t.car_poses()
            if poses:
                x, y = self._w2m(world, poses[0][0], poses[0][1], rect)
                pygame.draw.circle(screen, (230, 190, 90), (int(x), int(y)), 1)

        # revealed wildlife (don't reveal herds still hidden in fog)
        for a in sim.animals.list.values():
            if world.is_explored(int(round(a.x)), int(round(a.y))):
                x, y = self._w2m(world, a.x, a.y, rect)
                pygame.draw.circle(screen, (228, 86, 70), (int(x), int(y)), 1)

        hx, hy = self._w2m(world, 0, 0, rect)
        pygame.draw.circle(screen, (120, 190, 240), (int(hx), int(hy)), 3)
        for r in sim.robots.values():
            x, y = self._w2m(world, r.x, r.y, rect)
            pygame.draw.circle(screen, (120, 220, 235), (int(x), int(y)), 2)

        # camera viewport outline
        x0, y0, x1, y1 = cam.visible_tile_bounds()
        a = self._w2m(world, x0, y0, rect)
        b = self._w2m(world, x1, y1, rect)
        vr = pygame.Rect(int(a[0]), int(a[1]), max(2, int(b[0] - a[0])), max(2, int(b[1] - a[1])))
        vr.clamp_ip(rect)
        pygame.draw.rect(screen, (240, 240, 250), vr, 1)
        pygame.draw.rect(screen, (80, 86, 96), rect, 1)

    # ---- interaction ------------------------------------------------------
    def handle_click(self, pos, screen, cam, sim) -> bool:
        rect = self.rect(screen)
        if not rect.collidepoint(pos):
            return False
        wx, wy = self._m2w(sim.world, pos[0], pos[1], rect)
        cam.center_on(wx, wy)
        return True
