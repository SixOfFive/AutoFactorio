"""Tech research: sequential levels the director unlocks to advance.

Each tech spends its cost from the home inventory and applies a permanent
multiplier/bonus. The Simulation owns one Research instance and propagates the
current values to fields (drill rate), trains (speed/accel/capacity), furnaces
(smelting speed), rail cost, and the robot cap.
"""

from __future__ import annotations

from .. import balance


class Research:
    def __init__(self) -> None:
        self.level = 0
        self.completed: list[str] = []
        # live tuning values (start at the base balance numbers)
        self.drill_mult = 1.0
        self.train_speed = balance.TRAIN_MAX_SPEED
        self.train_accel = balance.TRAIN_ACCEL
        self.wagon_capacity = balance.CARGO_WAGON_CAPACITY
        self.furnace_mult = 1.0
        self.rail_discount = 1.0
        self.max_robots = balance.BASE_MAX_ROBOTS

    def next_tech(self) -> dict | None:
        return balance.TECHS[self.level] if self.level < len(balance.TECHS) else None

    def apply(self, tech: dict) -> None:
        for k, v in tech["effect"].items():
            if k == "drill_mult":
                self.drill_mult *= v
            elif k == "train_speed":
                self.train_speed *= v
            elif k == "train_accel":
                self.train_accel *= v
            elif k == "wagon_capacity":
                self.wagon_capacity = int(round(self.wagon_capacity * v))
            elif k == "furnace_mult":
                self.furnace_mult *= v
            elif k == "rail_discount":
                self.rail_discount *= v
            elif k == "max_robots":
                self.max_robots = min(3, self.max_robots + int(v))   # capped at 3 for now
        self.completed.append(tech["name"])
        self.level += 1

    # ---- persistence helpers ---------------------------------------------
    def to_dict(self) -> dict:
        return {
            "level": self.level, "completed": self.completed,
            "drill_mult": self.drill_mult, "train_speed": self.train_speed,
            "train_accel": self.train_accel, "wagon_capacity": self.wagon_capacity,
            "furnace_mult": self.furnace_mult, "rail_discount": self.rail_discount,
            "max_robots": self.max_robots,
        }

    def from_dict(self, d: dict) -> None:
        self.level = d.get("level", 0)
        self.completed = list(d.get("completed", []))
        self.drill_mult = d.get("drill_mult", 1.0)
        self.train_speed = d.get("train_speed", balance.TRAIN_MAX_SPEED)
        self.train_accel = d.get("train_accel", balance.TRAIN_ACCEL)
        self.wagon_capacity = d.get("wagon_capacity", balance.CARGO_WAGON_CAPACITY)
        self.furnace_mult = d.get("furnace_mult", 1.0)
        self.rail_discount = d.get("rail_discount", 1.0)
        self.max_robots = d.get("max_robots", balance.BASE_MAX_ROBOTS)
