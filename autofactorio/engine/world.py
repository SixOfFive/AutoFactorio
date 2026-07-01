"""The map: an ENDLESS procedurally-generated world - fog of war + ore patches.

Coordinates are integer tiles with HQ at (0, 0). The world is NOT a fixed square: it
starts as a MAP_RADIUS grid and GROWS (the `explored` fog canvas is re-centred on HQ and
enlarged) whenever exploration approaches the current edge. Ore patches are generated
deterministically per CELL the first time that cell is materialised (from a per-cell RNG
seeded by (seed, cell)), so the ore field is infinite yet reproducible and save-safe, and
patches get richer with distance so the frontier is always worth chasing. There is no end.

Fog is a single `explored` grid (numpy uint8): once a tile is revealed it stays revealed
(the base must remain visible) - black (unexplored) vs revealed, not Factorio's three-tier
charted/visible split. Keeping ONE growing grid (rather than sparse chunks) means the
renderer + minimap keep consuming `explored`/`radius`/`size` unchanged.
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
        self.radius = balance.MAP_RADIUS          # CURRENT grid half-size (grows over time)
        self.size = self.radius * 2 + 1
        self.rng = np.random.default_rng(seed)
        # fog: 0 = unexplored (black), 1 = revealed
        self.explored = np.zeros((self.size, self.size), dtype=np.uint8)
        self.patches: list[OrePatch] = []
        self._undiscovered: list[OrePatch] = []   # materialised but not yet revealed
        self.decor: list[tuple[int, int, str]] = []   # (tx, ty, 'tree'|'rock') scenery
        self.hq = (0, 0)
        self._starter_count = 0
        self._pid = 0
        self._cells_done: set[tuple[int, int]] = set()
        self.frontier_radius = float(balance.MAP_RADIUS)   # farthest revealed radius (spawn band)
        # ore type table for the per-cell RNG
        self._ores = list(balance.ORE_WEIGHTS.keys())
        w = np.array([balance.ORE_WEIGHTS[o] for o in self._ores], dtype=float)
        self._weights = w / w.sum()
        # guaranteed starters (one of each), then materialise the whole initial disk so the
        # early game has patches immediately (growth handles everything beyond it)
        self._place_starters()
        self._materialize_region(-self.radius, -self.radius, self.radius, self.radius)
        # the base sits in a barren clearing: reveal a small home area, then each (distant)
        # starter patch so the first tracks must be long
        self.reveal(0, 0, balance.SCOUT_REVEAL_RADIUS)
        for p in self.patches[:self._starter_count]:
            self.reveal(p.cx, p.cy, balance.SCOUT_REVEAL_RADIUS - 1)

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

    # ---- procedural generation (per-cell, deterministic, endless) ---------
    def _place_starters(self) -> None:
        """One patch of each resource, placed FAR from HQ in spread directions so the first
        tracks are long. Their cells are marked done so cell-gen never doubles up on them."""
        starters = [
            ("iron_ore", (32, 18)),
            ("copper_ore", (-30, 20)),
            ("coal", (20, -32)),
            ("stone", (-24, -28)),
        ]
        for ore, (cx, cy) in starters:
            base = balance.PATCH_RESERVE[ore]
            self._add_patch(ore, cx, cy, 3, base, base)
            self._cells_done.add(self._cell_of(cx, cy))
        self._starter_count = len(starters)

    def _add_patch(self, ore, cx, cy, rad, reserve, max_reserve) -> None:
        p = OrePatch(self._pid, ore, int(cx), int(cy), int(rad), int(reserve), int(max_reserve))
        self._pid += 1
        self.patches.append(p)
        self._undiscovered.append(p)

    @staticmethod
    def _cell_of(tx: int, ty: int) -> tuple[int, int]:
        c = balance.PATCH_CELL
        return (int(math.floor(tx / c)), int(math.floor(ty / c)))

    def _materialize_region(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Generate every not-yet-materialised cell overlapping the tile box [x0,y0]-[x1,y1]."""
        c = balance.PATCH_CELL
        for i in range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1):
            for j in range(int(math.floor(y0 / c)), int(math.floor(y1 / c)) + 1):
                if (i, j) not in self._cells_done:
                    self._gen_cell(i, j)

    def _gen_cell(self, i: int, j: int) -> None:
        """Deterministically populate cell (i, j): maybe one ore patch (richer the farther
        out) plus a little scenery. Seeded by (seed, cell) so it is identical no matter when
        the cell is first explored - the whole infinite field is reproducible from the seed."""
        self._cells_done.add((i, j))
        c = balance.PATCH_CELL
        # per-cell RNG (offset the signed cell coords into the non-negative seed space)
        rng = np.random.default_rng([self.seed & 0xFFFFFFFF, i + 0x40000000, j + 0x40000000])
        ox, oy = i * c, j * c
        if rng.random() < balance.PATCH_CELL_PROB:
            px = ox + int(rng.integers(3, c - 3))
            py = oy + int(rng.integers(3, c - 3))
            dist = math.hypot(px, py)
            if dist >= balance.PATCH_MIN_RING:            # keep the barren ring around HQ clear
                rad = int(rng.integers(balance.PATCH_RADIUS[0], balance.PATCH_RADIUS[1] + 1))
                ore = self._ores[int(rng.choice(len(self._ores), p=self._weights))]
                base = balance.PATCH_RESERVE[ore]
                rich = 1.0 + dist / balance.PATCH_RICH_SCALE      # frontier patches are richer
                reserve = int(base * rng.uniform(0.7, 1.4) * (0.7 + 0.15 * rad) * rich)
                self._add_patch(ore, px, py, rad, reserve, reserve)
        # scenery (revealed with the fog like everything else)
        for _ in range(int(rng.integers(2, 6))):
            dx, dy = ox + int(rng.integers(0, c)), oy + int(rng.integers(0, c))
            if dx * dx + dy * dy < 14 * 14:               # keep HQ clear
                continue
            self.decor.append((dx, dy, "tree" if rng.random() < 0.62 else "rock"))

    # ---- growth -----------------------------------------------------------
    def _grow(self, target_radius: int) -> None:
        """Enlarge the fog canvas (HQ stays centred) so tiles out to `target_radius` fit."""
        new_r = self.radius
        while new_r < target_radius:
            new_r += balance.WORLD_GROW_STEP
        old = self.explored
        off = new_r - self.radius
        self.radius = new_r
        self.size = new_r * 2 + 1
        self.explored = np.zeros((self.size, self.size), dtype=np.uint8)
        self.explored[off:off + old.shape[0], off:off + old.shape[1]] = old

    # ---- fog --------------------------------------------------------------
    def reveal(self, cx: float, cy: float, radius: float) -> list[OrePatch]:
        """Reveal a filled circle of tiles (growing the world + materialising ore cells as
        the frontier extends outward). Returns patches newly discovered."""
        r = int(math.ceil(radius))
        cxi, cyi = int(round(cx)), int(round(cy))
        # grow the canvas if this reveal reaches near the current edge
        need = max(abs(cxi), abs(cyi)) + r + balance.WORLD_GROW_MARGIN
        if need > self.radius:
            self._grow(need)
        # make sure the ore cells under/around this reveal exist before we test discovery
        self._materialize_region(cxi - r, cyi - r, cxi + r, cyi + r)
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
        self.frontier_radius = max(self.frontier_radius, math.hypot(cxi, cyi) + radius)
        return self._update_discovered()

    def _update_discovered(self) -> list[OrePatch]:
        """Promote any materialised-but-hidden patch that is now under revealed fog. Only the
        (small) undiscovered set is scanned, so this stays cheap as the world grows huge."""
        newly = []
        still = []
        for p in self._undiscovered:
            if self.is_explored(p.cx, p.cy):
                p.discovered = True
                newly.append(p)
            else:
                still.append(p)
        if newly:
            self._undiscovered = still
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
