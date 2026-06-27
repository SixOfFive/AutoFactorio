"""The map: terrain bounds, fog of war, and finite ore patches.

Coordinates are integer tiles with HQ at (0, 0); tiles range over
[-MAP_RADIUS, +MAP_RADIUS]. Fog is a single `explored` grid (numpy uint8):
once a tile is revealed by the scout it stays revealed (the base must remain
visible), so we use two states - black (unexplored) vs revealed - not Factorio's
three-tier charted/visible split.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .. import balance


@dataclass
class OrePatch:
    id: int
    ore: str                 # iron_ore | copper_ore | coal | stone
    cx: int                  # center tile
    cy: int
    radius: int
    reserve: int
    max_reserve: int
    discovered: bool = False
    claimed: bool = False     # a mining field has been built here

    @property
    def depleted(self) -> bool:
        return self.reserve <= 0

    def mine(self, amount: float) -> int:
        """Remove up to `amount` ore; returns the integer amount actually mined."""
        take = int(min(self.reserve, math.floor(amount)))
        self.reserve -= take
        return take


class World:
    def __init__(self, seed: int):
        self.seed = seed
        self.radius = balance.MAP_RADIUS
        self.size = self.radius * 2 + 1
        self.rng = np.random.default_rng(seed)
        # fog: 0 = unexplored (black), 1 = revealed
        self.explored = np.zeros((self.size, self.size), dtype=np.uint8)
        self.patches: list[OrePatch] = []
        self.decor: list[tuple[int, int, str]] = []   # (tx, ty, 'tree'|'rock') scenery
        self.hq = (0, 0)
        self._gen_patches()
        self._gen_decor()
        # reveal a generous area around HQ so the player starts with room to build
        self.reveal(0, 0, balance.SCOUT_REVEAL_RADIUS * 2)

    # ---- coordinate helpers ----------------------------------------------
    def in_bounds(self, tx: int, ty: int) -> bool:
        return -self.radius <= tx <= self.radius and -self.radius <= ty <= self.radius

    def _idx(self, tx: int, ty: int) -> tuple[int, int]:
        return ty + self.radius, tx + self.radius

    def is_explored(self, tx: int, ty: int) -> bool:
        if not self.in_bounds(tx, ty):
            return False
        gy, gx = self._idx(tx, ty)
        return bool(self.explored[gy, gx])

    # ---- generation -------------------------------------------------------
    def _gen_patches(self) -> None:
        ores = list(balance.ORE_WEIGHTS.keys())
        weights = np.array([balance.ORE_WEIGHTS[o] for o in ores], dtype=float)
        weights /= weights.sum()
        placed: list[tuple[int, int, int]] = []  # (cx, cy, radius)
        pid = 0
        # Guaranteed starters near HQ (within the initial reveal) so the logistics
        # loop can bootstrap immediately: iron to build with, coal to fuel trains.
        for ore, (cx, cy) in (("iron_ore", (14, 6)), ("coal", (-8, 14))):
            base = balance.PATCH_RESERVE[ore]
            self.patches.append(OrePatch(pid, ore, cx, cy, 3, base, base))
            placed.append((cx, cy, 3))
            pid += 1
        attempts = 0
        while len(self.patches) < balance.PATCH_COUNT and attempts < balance.PATCH_COUNT * 40:
            attempts += 1
            # bias toward a ring so patches spread outward, not clustered at center
            ang = self.rng.uniform(0, 2 * math.pi)
            dist = self.rng.uniform(balance.PATCH_MIN_RING, self.radius - 6)
            cx = int(round(math.cos(ang) * dist))
            cy = int(round(math.sin(ang) * dist))
            rad = int(self.rng.integers(balance.PATCH_RADIUS[0], balance.PATCH_RADIUS[1] + 1))
            if not self.in_bounds(cx, cy):
                continue
            # keep patches apart
            too_close = any((cx - px) ** 2 + (cy - py) ** 2 < (rad + pr + 6) ** 2
                            for px, py, pr in placed)
            if too_close:
                continue
            ore = ores[int(self.rng.choice(len(ores), p=weights))]
            base = balance.PATCH_RESERVE[ore]
            # vary reserve +-40%, scaled a little by footprint
            reserve = int(base * self.rng.uniform(0.6, 1.4) * (0.7 + 0.15 * rad))
            self.patches.append(OrePatch(pid, ore, cx, cy, rad, reserve, reserve))
            placed.append((cx, cy, rad))
            pid += 1

    def _gen_decor(self) -> None:
        """Scatter trees/rocks as scenery, away from HQ and ore patches. Revealed
        with the fog like everything else."""
        n = self.size * self.size // 220
        for _ in range(n):
            tx = int(self.rng.integers(-self.radius, self.radius + 1))
            ty = int(self.rng.integers(-self.radius, self.radius + 1))
            if tx * tx + ty * ty < 12 * 12:                     # keep HQ clear
                continue
            if any((tx - p.cx) ** 2 + (ty - p.cy) ** 2 < (p.radius + 3) ** 2
                   for p in self.patches):
                continue
            kind = "tree" if self.rng.random() < 0.62 else "rock"
            self.decor.append((tx, ty, kind))

    # ---- fog --------------------------------------------------------------
    def reveal(self, cx: float, cy: float, radius: float) -> list[OrePatch]:
        """Reveal a filled circle of tiles. Returns patches newly discovered."""
        r = int(math.ceil(radius))
        cxi, cyi = int(round(cx)), int(round(cy))
        x0 = max(-self.radius, cxi - r); x1 = min(self.radius, cxi + r)
        y0 = max(-self.radius, cyi - r); y1 = min(self.radius, cyi + r)
        if x0 > x1 or y0 > y1:
            return []
        gy0, gx0 = self._idx(x0, y0)
        gy1, gx1 = self._idx(x1, y1)
        ys = np.arange(y0, y1 + 1)[:, None]
        xs = np.arange(x0, x1 + 1)[None, :]
        mask = (xs - cxi) ** 2 + (ys - cyi) ** 2 <= radius * radius
        self.explored[gy0:gy1 + 1, gx0:gx1 + 1][mask] = 1
        return self._update_discovered()

    def _update_discovered(self) -> list[OrePatch]:
        newly = []
        for p in self.patches:
            if not p.discovered and self.is_explored(p.cx, p.cy):
                p.discovered = True
                newly.append(p)
        return newly

    # ---- queries ----------------------------------------------------------
    def discovered_patches(self) -> list[OrePatch]:
        return [p for p in self.patches if p.discovered and not p.depleted]

    def claimable_patches(self) -> list[OrePatch]:
        return [p for p in self.patches if p.discovered and not p.claimed and not p.depleted]

    def patch_by_id(self, pid: int) -> OrePatch | None:
        for p in self.patches:
            if p.id == pid:
                return p
        return None

    def nearest_unclaimed(self, tx: float, ty: float) -> OrePatch | None:
        cands = self.claimable_patches()
        if not cands:
            return None
        return min(cands, key=lambda p: (p.cx - tx) ** 2 + (p.cy - ty) ** 2)
