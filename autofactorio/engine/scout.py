"""The automated scout bot: drives outward from base in an expanding spiral,
revealing fog of war and discovering ore patches for the director to claim.
"""

from __future__ import annotations

import math

from .. import balance
from .world import World, OrePatch


class Scout:
    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.7              # current spiral angle (radians)
        self.radius = float(balance.PATCH_MIN_RING)
        self.tx, self.ty = self._target()
        self.heading = 0.0

    def _target(self) -> tuple[float, float]:
        return math.cos(self.angle) * self.radius, math.sin(self.angle) * self.radius

    def _next_target(self) -> None:
        # advance along an Archimedean-ish spiral so reveal circles overlap
        max_r = balance.MAP_RADIUS - balance.SCOUT_REVEAL_RADIUS - 2
        dtheta = max(0.25, balance.SCOUT_REVEAL_RADIUS / max(self.radius, 1.0))
        self.angle += dtheta
        if self.radius < max_r:
            self.radius = min(max_r, self.radius + balance.SCOUT_REVEAL_RADIUS * dtheta / (2 * math.pi) * 6)
        self.tx, self.ty = self._target()

    def update(self, dt: float, world: World) -> list[OrePatch]:
        dx = self.tx - self.x
        dy = self.ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            self._next_target()
            dx = self.tx - self.x
            dy = self.ty - self.y
            dist = math.hypot(dx, dy) or 1.0
        step = min(dist, balance.SCOUT_SPEED * dt)
        self.x += dx / dist * step
        self.y += dy / dist * step
        self.heading = math.degrees(math.atan2(dy, dx))
        return world.reveal(self.x, self.y, balance.SCOUT_REVEAL_RADIUS)

    @property
    def pos(self) -> tuple[float, float]:
        return self.x, self.y
