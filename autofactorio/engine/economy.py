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
    "train_stop", "electric_drill", "robot",   # robot kept ahead of the steel-hungry
    "assembler", "cargo_wagon", "locomotive",  # rolling stock so it actually gets made
    "solid_fuel", "rocket_fuel",  # convert surplus coal into denser train fuel
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
        # per-resource storage caps; items not listed are uncapped (transient
        # crafting intermediates). Clamp any starting overflow to the cap.
        self.caps: dict[str, int] = dict(balance.STORAGE_CAP_START)
        for k, c in self.caps.items():
            if self.inv.get(k, 0) > c:
                self.inv[k] = c
        self.furnaces = balance.HOME_START["furnaces"]
        self.furnace_tier = "stone"
        self.assemblers = balance.HOME_START["assemblers"]
        self._smelt_bank = 0.0
        self._craft_bank = 0.0
        # research multipliers, pushed in by the Simulation each tick
        self.research_furnace_mult = 1.0    # smelting speed
        self.research_craft_mult = 1.0      # crafting speed
        self.research_storage_mult = 1.0    # storage capacity (scales every cap)
        self.research_fuel_mult = 1.0       # fuel-efficiency (run-seconds per fuel unit)
        self.rocket_fuel_unlocked = False   # rocket-fuel processing researched yet?
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

    def add(self, item: str, qty: int) -> int:
        """Store up to `qty` of `item`, clamped to its storage cap. Returns the
        amount actually stored (the rest has nowhere to go - the caller decides
        whether that means overflow lost or back-pressure)."""
        if qty <= 0:
            return 0
        cap = self.cap_of(item)
        if cap is None:
            self.inv[item] += qty
            return qty
        cur = self.inv.get(item, 0)
        take = max(0, min(qty, cap - cur))
        if take:
            self.inv[item] = cur + take
        return take

    def cap_of(self, item: str) -> int | None:
        """Effective storage cap = the per-resource base (raised by built storage)
        times the research storage multiplier. None for uncapped intermediates."""
        base = self.caps.get(item)
        if base is None:
            return None
        return int(base * self.research_storage_mult)

    def fill_fraction(self, item: str) -> float:
        cap = self.cap_of(item)
        if not cap:
            return 0.0
        return self.inv.get(item, 0) / cap

    def is_full(self, item: str) -> bool:
        cap = self.cap_of(item)
        return cap is not None and self.inv.get(item, 0) >= cap

    def take_coal(self, n: int) -> int:
        return self.take("coal", n)

    def take(self, item: str, n: int) -> int:
        """Remove up to n of item; returns the amount actually removed."""
        n = min(int(n), self.inv.get(item, 0))
        if n > 0:
            self.inv[item] -= n
        return n

    def best_available_fuel(self) -> tuple[str | None, float]:
        """The densest fuel currently in stock and its run-seconds per unit (scaled
        by fuel-efficiency research). Trains/robots draw this first."""
        for f in balance.FUEL_ORDER:
            if self.inv.get(f, 0) > 0:
                return f, balance.FUEL_BURN[f] * self.research_fuel_mult
        return None, 0.0

    # ---- production -------------------------------------------------------
    def update(self, dt: float) -> None:
        # smelting & crafting throughput scale with research; the bank cap scales
        # too, else a tiny per-tick cap would throttle the tech multipliers away.
        fmult = self.research_furnace_mult
        self._smelt_bank = min(self._smelt_bank
                               + self.furnaces * balance.FURNACE_SPEED[self.furnace_tier]
                               * fmult * dt,
                               _SMELT_BANK_CAP * max(1.0, fmult))
        self._smelt()
        cmult = self.research_craft_mult
        self._craft_bank = min(self._craft_bank + self.assemblers * cmult * dt,
                               _CRAFT_BANK_CAP * max(1.0, cmult))
        self._craft()

    def _smelt(self) -> None:
        for name in _SMELT_ORDER:
            rec = balance.SMELT_RECIPES[name]
            out_item = next(iter(rec["out"]))
            cap = self.cap_of(out_item)
            while self._smelt_bank >= rec["time"] and self.have(rec["in"]):
                if cap is not None and self.inv.get(out_item, 0) >= cap:
                    break                              # storage for this plate is full
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
                # processed fuels: only convert SURPLUS coal (keep a reserve for
                # direct burning), and only make rocket fuel once it's researched
                if item == "rocket_fuel" and not self.rocket_fuel_unlocked:
                    continue
                if item in ("solid_fuel", "rocket_fuel") \
                        and self.inv.get("coal", 0) <= balance.FUEL_COAL_RESERVE:
                    continue
                cap = self.cap_of(item)
                if item == "science_pack":
                    # fill science to its (tech-scaled) storage cap so the next,
                    # ever-more-expensive research level can actually be funded
                    target = cap if cap is not None else balance.STOCK_TARGETS.get(item, 0)
                else:
                    # craft toward the stock target, but never past available storage
                    target = balance.STOCK_TARGETS.get(item, 0)
                    if cap is not None:
                        target = min(target, cap)
                if self.inv.get(item, 0) >= target:
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
