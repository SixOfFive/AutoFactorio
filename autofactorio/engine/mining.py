"""Mining fields: drills sitting on an ore patch, filling a load buffer.

A field mines its patch into a local buffer at the rate of its drills. A train
visiting the field's load station empties the buffer. When the patch is depleted
the field goes dead - the pressure that forces the network to keep expanding.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import balance
from .world import OrePatch


@dataclass
class MiningField:
    id: int
    patch: OrePatch
    drills: int
    tier: str                       # 'burner' | 'electric'
    load_station_id: int
    buffer: int = 0
    buffer_cap: int = 8000
    _accum: float = 0.0
    # for track reclamation when the field is abandoned
    edge_ids: list = field(default_factory=list)
    station_ids: list = field(default_factory=list)
    rail_used: int = 0
    # lifecycle: constructing (a robot is laying track + drills) -> active ->
    # recalling (trains heading home to storage) -> dismantling -> removed
    state: str = "active"

    @property
    def ore(self) -> str:
        return self.patch.ore

    @property
    def rate(self) -> float:
        return self.drills * balance.DRILL_RATE[self.tier]

    @property
    def active(self) -> bool:
        return not self.patch.depleted and self.buffer < self.buffer_cap

    def update(self, dt: float, rate_mult: float = 1.0) -> None:
        if self.patch.depleted or self.buffer >= self.buffer_cap:
            return
        self._accum += self.rate * rate_mult * dt
        whole = int(self._accum)
        if whole <= 0:
            return
        self._accum -= whole
        room = self.buffer_cap - self.buffer
        whole = min(whole, room)
        mined = self.patch.mine(whole)
        self.buffer += mined

    def take(self, amount: int) -> int:
        """Remove up to `amount` ore from the buffer; returns amount taken."""
        take = min(self.buffer, amount)
        self.buffer -= take
        return take
