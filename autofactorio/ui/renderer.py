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
GHOST_RAIL = (96, 110, 96)        # planned track a robot has not yet laid
ARROW = (210, 214, 110)
FOG = (7, 9, 14)
SIG_GREEN = (90, 220, 110)
SIG_RED = (228, 86, 70)


class Renderer:
    def __init__(self, assets: Assets):
        self.a = assets

    # ---- public -----------------------------------------------------------
    def draw(self, screen: pygame.Surface, cam, sim, selected=None) -> None:
        screen.fill(GRASS)
        self._decor(screen, cam, sim)
        self._patches(screen, cam, sim)
        self._rails(screen, cam, sim)
        self._stations(screen, cam, sim)
        self._fields(screen, cam, sim)
        self._home(screen, cam, sim)
        self._trains(screen, cam, sim)
        self._animals(screen, cam, sim)
        self._robots(screen, cam, sim)
        self._selection(screen, cam, sim, selected)
        self._fog(screen, cam, sim.world)

    def _decor(self, screen, cam, sim):
        world = sim.world
        x0, y0, x1, y1 = cam.visible_tile_bounds(margin=2)
        for (tx, ty, kind) in world.decor:
            if tx < x0 or tx > x1 or ty < y0 or ty > y1:
                continue
            if not world.is_explored(tx, ty):
                continue
            self._blit(screen, cam, kind, tx, ty, 1.7)

    def _selection(self, screen, cam, sim, selected):
        if not selected:
            return
        kind, sid = selected
        pos = None
        if kind == "train":
            t = sim.trains.get(sid)
            if t:
                poses = t.car_poses()
                if poses:
                    pos = (poses[0][0], poses[0][1])
        elif kind == "field":
            f = sim.fields.get(sid)
            if f:
                pos = (f.patch.cx, f.patch.cy)
        if pos is None:
            return
        sx, sy = cam.world_to_screen(*pos)
        r = max(8, int(2.2 * cam.zoom))
        pygame.draw.circle(screen, (250, 240, 120), (int(sx), int(sy)), r, 2)

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
    _ORE_SPRITE = {"iron_ore": "ore_iron", "copper_ore": "ore_copper",
                   "coal": "ore_coal", "stone": "ore_stone"}

    def _patches(self, screen, cam, sim):
        for p in sim.world.patches:
            if not p.discovered:
                continue
            tiles = p.radius * 2 + 1
            if p.depleted:
                self._blit(screen, cam, "rock", p.cx, p.cy, tiles)   # spent ground
            else:
                self._blit(screen, cam, self._ORE_SPRITE.get(p.ore, "ore_iron"),
                           p.cx, p.cy, tiles)

    def _rails(self, screen, cam, sim):
        zoom = cam.zoom
        bed_w = max(2, int(0.55 * zoom))
        top_w = max(1, int(0.26 * zoom))
        draw_arrows = zoom >= 9
        for e in sim.net.edges.values():
            pts = [cam.world_to_screen(x, y) for (x, y) in e.points]
            if not any(self._on(cam, sx, sy, 40) for sx, sy in pts):
                continue
            if not e.built:                                   # planned/ghost track
                pygame.draw.lines(screen, GHOST_RAIL, False, pts, max(1, top_w))
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
            if getattr(f, "state", "active") == "constructing":
                continue                                  # drills not placed until built
            p = f.patch
            n = min(f.drills, 6)
            cols = 3
            for i in range(n):
                gx = (i % cols) - 1
                gy = (i // cols) - 0.5
                self._blit(screen, cam, "mining_drill",
                           p.cx + gx * 1.6, p.cy + gy * 1.6, 1.5)
            if cam.zoom >= 6 and p.max_reserve:
                self._bar(screen, cam, p.cx, p.cy - p.radius - 1.2,
                          p.reserve / p.max_reserve, (110, 200, 120))

    def _bar(self, screen, cam, wx, wy, frac, color):
        """A small world-anchored progress bar (reserve, cargo, ...)."""
        frac = max(0.0, min(1.0, frac))
        sx, sy = cam.world_to_screen(wx, wy)
        if not self._on(cam, sx, sy):
            return
        w = max(14, int(2.6 * cam.zoom))
        h = max(3, int(0.28 * cam.zoom))
        x = int(sx - w / 2)
        y = int(sy - h / 2)
        pygame.draw.rect(screen, (18, 20, 26), (x - 1, y - 1, w + 2, h + 2))
        pygame.draw.rect(screen, (60, 64, 72), (x, y, w, h))
        pygame.draw.rect(screen, color, (x, y, int(w * frac), h))

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
            loco_pose = None
            for (wx, wy, ang, kind) in t.car_poses():
                sx, sy = cam.world_to_screen(wx, wy)
                if kind == "loco":
                    loco_pose = (wx, wy)
                if not self._on(cam, sx, sy):
                    continue
                lp = max(2, int(length * cam.zoom))
                wp = max(2, int(balance.ENTITY_WIDTH * cam.zoom))
                sprite = "locomotive" if kind == "loco" else "wagon"
                base = pygame.transform.smoothscale(self.a.base[sprite], (lp, wp))
                img = pygame.transform.rotate(base, -ang)
                screen.blit(img, img.get_rect(center=(sx, sy)))
                if t.stalled and kind == "loco":
                    pygame.draw.circle(screen, SIG_RED, (int(sx), int(sy)),
                                       max(3, int(0.5 * cam.zoom)), 2)
            if loco_pose and cam.zoom >= 6:
                if t.capacity:
                    self._bar(screen, cam, loco_pose[0], loco_pose[1] - 2.2,
                              t.cargo_total() / t.capacity, (230, 190, 90))
                if t.hp < t.max_hp:
                    self._bar(screen, cam, loco_pose[0], loco_pose[1] - 2.9,
                              t.hp / t.max_hp, (228, 86, 70))

    def _robots(self, screen, cam, sim):
        for r in sim.robots.values():
            self._blit(screen, cam, "scout", r.x, r.y, 2.4, angle=-r.heading)
            if cam.zoom >= 6 and r.hp < balance.ROBOT_HP:
                self._bar(screen, cam, r.x, r.y - 1.8, r.hp / balance.ROBOT_HP, (110, 200, 230))

    def _animals(self, screen, cam, sim):
        for a in sim.animals.list.values():
            self._blit(screen, cam, "animal", a.x, a.y, 2.0)
            if a.state == "attack":
                sx, sy = cam.world_to_screen(a.x, a.y)
                if self._on(cam, sx, sy):
                    pygame.draw.circle(screen, SIG_RED, (int(sx), int(sy)),
                                       max(3, int(1.1 * cam.zoom)), 1)

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
