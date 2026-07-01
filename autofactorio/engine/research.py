"""Tech research: 1000 levels the director unlocks one at a time.

`level` is the single source of truth; every live multiplier is COMPUTED from it
via the closed-form curves in `balance` (so 1000 levels need no per-tech tables
and save/load is just an int). The Simulation spends the next level's science
cost, calls `advance()`, and reads these values for fields, trains, furnaces,
crafting, storage, construction and the robot cap.
"""

from __future__ import annotations

from .. import balance


class Research:
    def __init__(self) -> None:
        self.level = 0

    # ---- computed live tuning (all derived from self.level) ---------------
    @property
    def drill_mult(self) -> float:
        return balance.mining_mult(self.level)

    @property
    def train_speed(self) -> float:
        return balance.TRAIN_MAX_SPEED * balance.train_speed_mult(self.level)

    @property
    def train_accel(self) -> float:
        return balance.TRAIN_ACCEL * balance.train_accel_mult(self.level)

    @property
    def wagon_capacity(self) -> int:
        return int(round(balance.CARGO_WAGON_CAPACITY * balance.wagon_mult(self.level)))

    @property
    def furnace_mult(self) -> float:
        return balance.furnace_mult(self.level)

    @property
    def craft_mult(self) -> float:
        return balance.craft_mult(self.level)

    @property
    def storage_mult(self) -> float:
        return balance.storage_mult(self.level)

    @property
    def unload_mult(self) -> float:
        return balance.unload_mult(self.level)

    @property
    def construction_mult(self) -> float:
        return balance.construction_mult(self.level)

    @property
    def rail_discount(self) -> float:
        return balance.rail_discount(self.level)

    @property
    def max_robots(self) -> int:
        return balance.max_robots(self.level)

    @property
    def fuel_efficiency(self) -> float:
        return balance.fuel_efficiency(self.level)

    @property
    def nuclear_fuel_unlocked(self) -> bool:
        return self.level >= balance.NUCLEAR_FUEL_TECH

    @property
    def fusion_fuel_unlocked(self) -> bool:
        return self.level >= balance.FUSION_FUEL_TECH

    @property
    def spaceflight(self) -> bool:
        return self.level >= balance.SPACE_TECH_LEVEL

    # ---- progression ------------------------------------------------------
    def next_tech(self) -> dict | None:
        return balance.tech_for_level(self.level + 1)

    def advance(self) -> None:
        if self.level < balance.MAX_TECH_LEVEL:
            self.level += 1

    # ---- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return {"level": self.level}

    def from_dict(self, d: dict) -> None:
        self.level = int(d.get("level", 0))
