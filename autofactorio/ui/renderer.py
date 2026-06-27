"""World renderer: terrain, ore, one-way rails, stations, fields, home factory,
trains, scout, and the fog-of-war overlay. Everything goes through the camera
transform; the viewport is culled so map size doesn't cost frames.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from .. import balance
from .assets import Assets

GRASS = (74, 116, 62)
RAIL_BED = (52, 50, 54)
RAIL_TOP = (150, 156, 165)
ARROW = (210, 214, 110)
FOG = (7, 9, 14)
SIG_GREEN = (90, 220, 110)
SIG_RED = (228, 86, 70)


class Renderer:
    def __init__(self, assets: Assets):
        self.a = assets

    # ---- public -----------------------------------------------------------
    def draw(self, screen: pygame.Surface, cam, sim) -> None:
        screen.fill(GRASS)
        self._patches(screen, cam, sim)
        self._rails(screen, cam, sim)
        self._stations(screen, cam, sim)
        self._fields(screen, cam, sim)
        self._home(screen, cam, sim)
        self._trains(screen, cam, sim)
        self._scout(screen, cam, sim)
        self._fog(screen, cam, sim.world)

    # ---- helpers ----------------------------------------------------------
    def _on(self, cam, sx, sy, pad=80) -> bool:
        return -pad <= sx <= cam.screen_w + pad and -pad <= sy <= cam.screen_h + pad

    def _blit(self, screen, cam, name, wx, wy, tiles, angle=None):
        px = max(1, int(tiles * cam.zoom))
        sx, sy = cam.world_to_screen(wx, wy)
        if not self._on(cam, sx, sy):
            return
        img = self.a.scaled(name, px) if angle is None else self.a.rotated(name, px, angle)
        screen.blit(img, img.get_rect(center=(sx, sy)))

    # ---- layers -----------------------------------------------------------
    def _patches(self, screen, cam, sim):
        for p in sim.world.patches:
            if not p.discovered:
                continue
            tiles = p.radius * 2 + 1
            name = f"ore_{p.ore.split('_')[0]}" if p.ore != "coal" else "ore_coal"
            if p.ore == "iron_ore":
                name = "ore_iron"
            elif p.ore == "copper_ore":
                name = "ore_copper"
            elif p.ore == "stone":
                name = "ore_stone"
            self._blit(screen, cam, name, p.cx, p.cy, tiles)

    def _rails(self, screen, cam, sim):
        zoom = cam.zoom
        bed_w = max(2, int(0.55 * zoom))
        top_w = max(1, int(0.26 * zoom))
        draw_arrows = zoom >= 9
        for e in sim.net.edges.values():
            pts = [cam.world_to_screen(x, y) for (x, y) in e.points]
            if not any(self._on(cam, sx, sy, 40) for sx, sy in pts):
                continue
            pygame.draw.lines(screen, RAIL_BED, False, pts, bed_w)
            pygame.draw.lines(screen, RAIL_TOP, False, pts, top_w)
            if draw_arrows and len(pts) >= 2:
                self._arrow(screen, pts[0], pts[-1], zoom)

    def _arrow(self, screen, a, b, zoom):
        mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        size = max(3, 0.32 * zoom)
        tip = (mx + math.cos(ang) * size, my + math.sin(ang) * size)
        left = (mx + math.cos(ang + 2.5) * size, my + math.sin(ang + 2.5) * size)
        right = (mx + math.cos(ang - 2.5) * size, my + math.sin(ang - 2.5) * size)
        pygame.draw.polygon(screen, ARROW, [tip, left, right])

    def _stations(self, screen, cam, sim):
        show_sig = cam.zoom >= 8
        if show_sig:
            for nid, sig in sim.net.signals.items():
                sx, sy = cam.world_to_screen(*sig.pos)
                if not self._on(cam, sx, sy):
                    continue
                occ = False
                for eid in sim.net.out_edges.get(nid, []):
                    blk = sim.net.blocks.get(sim.net.edges[eid].block_id)
                    if blk and blk.occupant is not None:
                        occ = True
                        break
                col = SIG_RED if occ else SIG_GREEN
                r = max(2, int(0.16 * cam.zoom))
                pygame.draw.circle(screen, (10, 12, 16), (int(sx), int(sy)), r + 1)
                pygame.draw.circle(screen, col, (int(sx), int(sy)), r)
        for st in sim.net.stations.values():
            self._blit(screen, cam, "train_stop", st.pos[0], st.pos[1], 2.0)

    def _fields(self, screen, cam, sim):
        for f in sim.fields.values():
            p = f.patch
            n = min(f.drills, 6)
            cols = 3
            for i in range(n):
                gx = (i % cols) - 1
                gy = (i // cols) - 0.5
                self._blit(screen, cam, "mining_drill",
                           p.cx + gx * 1.6, p.cy + gy * 1.6, 1.5)

    def _home(self, screen, cam, sim):
        self._blit(screen, cam, "hq", 0, 0, 4.5)
        # ring of furnaces + assemblers representing the home factory
        nf = min(sim.economy.furnaces, 10)
        na = min(sim.economy.assemblers, 10)
        for i in range(nf):
            a = i / max(1, nf) * 2 * math.pi
            self._blit(screen, cam, "smelter", math.cos(a) * 4.5, math.sin(a) * 4.5, 1.6)
        for i in range(na):
            a = i / max(1, na) * 2 * math.pi + 0.3
            self._blit(screen, cam, "assembler", math.cos(a) * 6.8, math.sin(a) * 6.8, 1.6)

    def _trains(self, screen, cam, sim):
        length = balance.ENTITY_LEN
        for t in sim.trains.values():
            for (wx, wy, ang, kind) in t.car_poses():
                sx, sy = cam.world_to_screen(wx, wy)
                if not self._on(cam, sx, sy):
                    continue
                lp = max(2, int(length * cam.zoom))
                wp = max(2, int(2.6 * cam.zoom))
                sprite = "locomotive" if kind == "loco" else "wagon"
                base = pygame.transform.smoothscale(self.a.base[sprite], (lp, wp))
                img = pygame.transform.rotate(base, -ang)
                screen.blit(img, img.get_rect(center=(sx, sy)))
                if t.stalled and kind == "loco":
                    pygame.draw.circle(screen, SIG_RED, (int(sx), int(sy)),
                                       max(3, int(0.5 * cam.zoom)), 2)

    def _scout(self, screen, cam, sim):
        sc = sim.scout
        self._blit(screen, cam, "scout", sc.x, sc.y, 2.4, angle=-sc.heading)

    # ---- fog of war -------------------------------------------------------
    def _fog(self, screen, cam, world):
        x0, y0, x1, y1 = cam.visible_tile_bounds(margin=1)
        w = x1 - x0 + 1
        h = y1 - y0 + 1
        if w <= 0 or h <= 0:
            return
        R = world.radius
        alpha = np.full((h, w), 255, dtype=np.uint8)        # default: unexplored
        mx0, mx1 = max(x0, -R), min(x1, R)
        my0, my1 = max(y0, -R), min(y1, R)
        if mx0 <= mx1 and my0 <= my1:
            sub = world.explored[my0 + R:my1 + R + 1, mx0 + R:mx1 + R + 1]
            ay, ax = my0 - y0, mx0 - x0
            alpha[ay:ay + sub.shape[0], ax:ax + sub.shape[1]] = np.where(sub == 1, 0, 255)
        fog = pygame.Surface((w, h), pygame.SRCALPHA)
        fog.fill((*FOG, 255))
        pa = pygame.surfarray.pixels_alpha(fog)
        pa[:, :] = alpha.T
        del pa
        target = (max(1, int(w * cam.zoom)), max(1, int(h * cam.zoom)))
        scaled = pygame.transform.scale(fog, target)
        sx, sy = cam.world_to_screen(x0 - 0.5, y0 - 0.5)
        screen.blit(scaled, (sx, sy))
