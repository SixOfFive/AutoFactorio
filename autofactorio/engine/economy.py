"""Home base economy: inventory, smelting, and the auto-crafter.

Trains unload raw ore here. Furnaces smelt ore -> plates; assemblers craft the
intermediate chain and buildables (rails, drills, rolling stock) up to stock
targets. The director then SPENDS that stock to expand the network - mirroring
SimCity_LLM's "LLM owns strategy, deterministic systems own mechanics" split.

Production work is banked across ticks: at 60 fps a single tick only buys
~assemblers*dt seconds of work, far less than a recipe's time, so leftover work
must accumulate or nothing would ever be produced. Banks are capped so a backlog
can't dump in one frame when inputs finally arrive.

Furnace fuel is abstracted (assume powered); coal's meaningful sink is train
fuel, so a mis-managed network still feels the coal dependency without per-field
coal logistics.
"""

from __future__ import annotations

from collections import defaultdict

from .. import balance

# Smelt in this order; steel only when iron plate is in surplus (it eats 5 each).
_SMELT_ORDER = ["iron_plate", "copper_plate", "steel_plate"]
# Craft toward stock in this order; intermediates are made on demand.
_BUILD_ORDER = [
    "stone_furnace", "rail", "rail_signal", "chain_signal",
    "train_stop", "electric_drill", "assembler", "cargo_wagon", "locomotive",
    "science_pack",     # made from surplus circuits/plates; fuels research
]
_IRON_RESERVE_FOR_STEEL = 40       # keep this many iron plates before making steel
_SMELT_BANK_CAP = 64.0             # max furnace-seconds banked
_CRAFT_BANK_CAP = 16.0             # max assembler-seconds banked


class Economy:
    def __init__(self) -> None:
        self.inv: dict[str, int] = defaultdict(int)
        for k, v in balance.STARTING_INVENTORY.items():
            self.inv[k] += v
        self.furnaces = balance.HOME_START["furnaces"]
        self.furnace_tier = "stone"
        self.assemblers = balance.HOME_START["assemblers"]
        self._smelt_bank = 0.0
        self._craft_bank = 0.0
        self.research_furnace_mult = 1.0    # lifted by Electric Smelting research
        self.total_smelted = 0
        self.total_crafted = 0

    # ---- inventory helpers ------------------------------------------------
    def have(self, costs: dict[str, int]) -> bool:
        return all(self.inv.get(k, 0) >= v for k, v in costs.items())

    def spend(self, costs: dict[str, int]) -> bool:
        if not self.have(costs):
            return False
        for k, v in costs.items():
            self.inv[k] -= v
        return True

    def add(self, item: str, qty: int) -> None:
        self.inv[item] += qty

    def take_coal(self, n: int) -> int:
        n = min(n, self.inv.get("coal", 0))
        self.inv["coal"] -= n
        return n

    # ---- production -------------------------------------------------------
    def update(self, dt: float) -> None:
        self._smelt_bank = min(self._smelt_bank
                               + self.furnaces * balance.FURNACE_SPEED[self.furnace_tier]
                               * self.research_furnace_mult * dt,
                               _SMELT_BANK_CAP)
        self._smelt()
        self._craft_bank = min(self._craft_bank + self.assemblers * dt, _CRAFT_BANK_CAP)
        self._craft()

    def _smelt(self) -> None:
        for name in _SMELT_ORDER:
            rec = balance.SMELT_RECIPES[name]
            while self._smelt_bank >= rec["time"] and self.have(rec["in"]):
                if name == "steel_plate" and self.inv.get("iron_plate", 0) <= _IRON_RESERVE_FOR_STEEL:
                    break
                for ing, q in rec["in"].items():
                    self.inv[ing] -= q
                for out, q in rec["out"].items():
                    self.inv[out] += q
                    self.total_smelted += q
                self._smelt_bank -= rec["time"]

    def _craft(self) -> None:
        # Round-robin across all buildables so an expensive item at the end of the
        # list (locomotives, wagons) still gets budget instead of being starved by
        # the hungry early targets (rails, drills). One unit per item per pass.
        guard = 0
        progress = True
        while self._craft_bank > 0 and progress and guard < 500:
            guard += 1
            progress = False
            for item in _BUILD_ORDER:
                if self.inv.get(item, 0) >= balance.STOCK_TARGETS.get(item, 0):
                    continue
                if self._try_craft(item, depth=0):
                    progress = True
                if self._craft_bank <= 0:
                    break

    def _try_craft(self, item: str, depth: int) -> bool:
        """Craft one `item`, recursively making missing craftable intermediates.
        Plates/ores aren't craftable here (smelting/trains provide them), so a raw
        shortage simply fails. Returns True if a unit was produced."""
        if depth > 6 or item not in balance.RECIPES:
            return False
        rec = balance.RECIPES[item]
        for ing, q in rec["in"].items():
            while self.inv.get(ing, 0) < q:
                if not self._try_craft(ing, depth + 1):
                    return False
        if self._craft_bank < rec["time"] or not self.have(rec["in"]):
            return False
        for ing, q in rec["in"].items():
            self.inv[ing] -= q
        for out, q in rec["out"].items():
            self.inv[out] += q
            self.total_crafted += q
        self._craft_bank -= rec["time"]
        return True
