"""Simulation: the authoritative game state and tick loop.

Owns the world, economy, rail network, fields, trains, and scout. Exposes the
high-level build actions the director calls (these are the deterministic
"autopilot" that guarantees connectivity + collision-free routing) plus a
compact state snapshot for the LLM report and the HUD.
"""

from __future__ import annotations

import math

from .. import balance
from .economy import Economy
from .mining import MiningField
from .rail import RailNetwork
from .scout import Scout
from .trains import Train, Leg
from .world import World

LOAD_RATE = 800.0      # items/sec a train (un)loads at a stop
UNLOAD_RATE = 800.0
WAIT_IDLE = 6.0        # secs with no transfer before a train gives up waiting
LOAD_MAX_DWELL = 30.0  # secs a train will sit loading before leaving with a partial load
HOME = (0, 0)


class Simulation:
    def __init__(self, config):
        self.config = config
        self.world = World(config.seed)
        self.economy = Economy()
        self.net = RailNetwork()
        self.scout = Scout()
        self.fields: dict[int, MiningField] = {}
        self.trains: dict[int, Train] = {}
        self._fid = 0
        self._tid = 0
        self.time = 0.0
        self.speed = balance.DEFAULT_GAME_SPEED
        self.paused = False
        self.events: list[tuple[float, str]] = []
        self.delivered_total = 0
        self._depleted_announced: set[int] = set()
        self.log("Base online. Scout dispatched to map the frontier.")

    # ---- logging ----------------------------------------------------------
    def log(self, text: str) -> None:
        self.events.append((self.time, text))
        if len(self.events) > 400:
            self.events = self.events[-300:]

    # ---- main tick --------------------------------------------------------
    def tick(self, real_dt: float) -> None:
        if self.paused:
            return
        dt = real_dt * self.speed
        if dt <= 0:
            return
        self.time += dt

        for patch in self.scout.update(dt, self.world):
            self.log(f"Scout discovered a {patch.ore.replace('_', ' ')} patch "
                     f"(#{patch.id}) at ({patch.cx}, {patch.cy}).")

        for f in self.fields.values():
            f.update(dt)
            if f.patch.depleted and f.id not in self._depleted_announced:
                self._depleted_announced.add(f.id)
                self.log(f"Field #{f.id} ({f.patch.ore.replace('_', ' ')}) patch is exhausted.")
        self.economy.update(dt)

        for t in self.trains.values():
            t.update_movement(dt, self.net)
            if t.state == "waiting":
                self._service_station(t, dt)

    # ---- station servicing ------------------------------------------------
    def _service_station(self, train: Train, dt: float) -> None:
        st = self.net.stations[train.current_station_id]
        self._refuel(train)
        leg = train.legs[train.cur_leg]
        moved = 0
        if st.kind == "load":
            field = self.fields.get(st.field_id)
            if field is not None:
                want = min(train.cargo_free(), int(LOAD_RATE * dt) + 1)
                got = field.take(want)
                if got:
                    train.cargo[field.ore] = train.cargo.get(field.ore, 0) + got
                    moved = got
        elif st.kind == "unload":
            budget = int(UNLOAD_RATE * dt) + 1
            for item in list(train.cargo.keys()):
                mv = min(train.cargo[item], budget)
                if mv <= 0:
                    continue
                train.cargo[item] -= mv
                if train.cargo[item] == 0:
                    del train.cargo[item]
                self.economy.add(item, mv)
                self.delivered_total += mv
                moved += mv
                budget -= mv
                if budget <= 0:
                    break

        train.idle_timer = 0.0 if moved > 0 else train.idle_timer + dt
        train.wait_timer += dt
        if self._wait_satisfied(train, leg):
            train.depart(self.net)

    def _wait_satisfied(self, train: Train, leg: Leg) -> bool:
        kind = leg.wait[0]
        if kind == "full_cargo":
            if train.cargo_total() >= train.capacity:
                return True
            if train.cargo_total() > 0 and (train.idle_timer >= WAIT_IDLE
                                            or train.wait_timer >= LOAD_MAX_DWELL):
                return True
            # nothing to load (e.g. depleted patch): don't wait forever
            return train.idle_timer >= WAIT_IDLE * 2
        if kind == "empty_cargo":
            return train.cargo_total() == 0 or train.idle_timer >= WAIT_IDLE
        if kind == "time":
            return train.wait_timer >= leg.wait[1]
        return True

    def _refuel(self, train: Train) -> None:
        cap = balance.LOCO_FUEL_SLOTS * balance.COAL_BURN_SECONDS
        if train.fuel_seconds >= cap - balance.COAL_BURN_SECONDS:
            return
        need = int((cap - train.fuel_seconds) / balance.COAL_BURN_SECONDS)
        got = self.economy.take_coal(need)
        train.fuel_seconds += got * balance.COAL_BURN_SECONDS

    # ---- build actions (the deterministic autopilot) ----------------------
    def choose_tier(self) -> str:
        return ("electric" if self.economy.inv.get("electric_drill", 0) >= balance.DEFAULT_FIELD_DRILLS
                else "burner")

    def field_cost(self, patch, tier: str) -> dict[str, int]:
        drill_item = "electric_drill" if tier == "electric" else "burner_drill"
        dist = math.dist(HOME, (patch.cx, patch.cy))
        rails_needed = int(dist * 1.15) + 10
        signals_needed = max(2, rails_needed // balance.SIGNAL_SPACING)
        return {
            drill_item: balance.DEFAULT_FIELD_DRILLS,
            "train_stop": 2,
            "rail": rails_needed,
            "rail_signal": signals_needed,
            "locomotive": 1,
            "cargo_wagon": balance.DEFAULT_WAGONS,
        }

    def can_build_field(self, patch) -> bool:
        if patch is None or patch.claimed or patch.depleted or not patch.discovered:
            return False
        return self.economy.have(self.field_cost(patch, self.choose_tier()))

    def build_field(self, patch_id: int, tier: str | None = None) -> tuple[bool, str]:
        patch = self.world.patch_by_id(patch_id)
        if patch is None:
            return False, f"no patch #{patch_id}"
        if patch.claimed:
            return False, f"patch #{patch_id} already claimed"
        if patch.depleted or not patch.discovered:
            return False, f"patch #{patch_id} not available"

        if tier not in ("burner", "electric"):
            tier = self.choose_tier()

        rails_needed = self.field_cost(patch, tier)["rail"]
        costs = self.field_cost(patch, tier)
        if not self.economy.have(costs):
            missing = {k: v for k, v in costs.items() if self.economy.inv.get(k, 0) < v}
            return False, f"insufficient materials for field: need {missing}"

        out_e, ret_e, load_st, unload_st = self.net.build_link(HOME, (patch.cx, patch.cy))
        fid = self._fid
        self._fid += 1
        field = MiningField(fid, patch, balance.DEFAULT_FIELD_DRILLS, tier, load_st.id)
        load_st.field_id = fid
        load_st.name = f"{patch.ore}-{fid}-load"
        unload_st.name = f"home-{fid}-unload"
        patch.claimed = True
        self.fields[fid] = field

        legs = [
            Leg(out_e, load_st.id, ("full_cargo",)),
            Leg(ret_e, unload_st.id, ("empty_cargo",)),
        ]
        tid = self._tid
        self._tid += 1
        self.trains[tid] = Train(tid, legs, balance.DEFAULT_WAGONS, self.net)

        self.economy.spend(costs)
        self.log(f"Built {tier} mining field #{fid} on {patch.ore.replace('_', ' ')} "
                 f"patch #{patch_id}; laid {rails_needed} rail, dispatched train #{tid}.")
        return True, f"field #{fid} on patch #{patch_id} ({patch.ore})"

    def add_train(self, field_id: int) -> tuple[bool, str]:
        """Add throughput to a field by building a SECOND independent parallel
        loop (its own one-way lanes + stations + train) to the same patch. Keeping
        loops dedicated means no shared blocks, so it stays collision/deadlock-free."""
        field = self.fields.get(field_id)
        if field is None:
            return False, f"no field #{field_id}"
        patch = field.patch
        dist = math.dist(HOME, (patch.cx, patch.cy))
        rails_needed = int(dist * 1.15) + 10
        signals_needed = max(2, rails_needed // balance.SIGNAL_SPACING)
        costs = {
            "train_stop": 2,
            "rail": rails_needed,
            "rail_signal": signals_needed,
            "locomotive": 1,
            "cargo_wagon": balance.DEFAULT_WAGONS,
        }
        if not self.economy.have(costs):
            return False, "insufficient materials for a second loop"
        out_e, ret_e, load_st, unload_st = self.net.build_link(HOME, (patch.cx, patch.cy))
        load_st.field_id = field_id
        load_st.name = f"{patch.ore}-{field_id}-load2"
        unload_st.name = f"home-{field_id}-unload2"
        legs = [
            Leg(out_e, load_st.id, ("full_cargo",)),
            Leg(ret_e, unload_st.id, ("empty_cargo",)),
        ]
        tid = self._tid
        self._tid += 1
        self.trains[tid] = Train(tid, legs, balance.DEFAULT_WAGONS, self.net)
        self.economy.spend(costs)
        self.log(f"Added a second loop + train #{tid} to field #{field_id}.")
        return True, f"second train #{tid} added to field #{field_id}"

    def abandon_field(self, field_id: int) -> tuple[bool, str]:
        """Retire a field (usually a depleted patch): remove its trains, salvage
        their locomotives + wagons back to stock, and release any block locks they
        held. Rails are left in place. The patch frees up for re-claim if it still
        has reserve."""
        field = self.fields.get(field_id)
        if field is None:
            return False, f"no field #{field_id}"
        removed = 0
        salvaged_wagons = 0
        for tid in list(self.trains.keys()):
            t = self.trains[tid]
            st = self.net.stations.get(t.legs[0].station_id)
            if st is not None and st.field_id == field_id:
                for bid in list(t.locked):
                    blk = self.net.blocks.get(bid)
                    if blk is not None and blk.occupant == t.id:
                        blk.occupant = None
                self.economy.add("locomotive", 1)
                self.economy.add("cargo_wagon", t.wagons)
                salvaged_wagons += t.wagons
                del self.trains[tid]
                removed += 1
        del self.fields[field_id]
        self._depleted_announced.discard(field_id)
        if not field.patch.depleted:
            field.patch.claimed = False           # reclaimable if ore remains
        self.log(f"Abandoned field #{field_id}; salvaged {removed} locomotive(s) "
                 f"and {salvaged_wagons} wagon(s).")
        return True, f"abandoned field #{field_id} (salvaged {removed} train(s))"

    def build_assembler(self, n: int = 1) -> tuple[bool, str]:
        if not self.economy.spend({"assembler": n}):
            return False, "no assemblers in stock"
        self.economy.assemblers += n
        self.log(f"Deployed {n} assembler(s); home now has {self.economy.assemblers}.")
        return True, f"assemblers now {self.economy.assemblers}"

    def build_furnace(self, n: int = 1) -> tuple[bool, str]:
        if not self.economy.spend({"stone_furnace": n}):
            return False, "no furnaces in stock"
        self.economy.furnaces += n
        self.log(f"Deployed {n} furnace(s); home now has {self.economy.furnaces}.")
        return True, f"furnaces now {self.economy.furnaces}"

    def expand_drills(self, field_id: int, n: int = 2) -> tuple[bool, str]:
        field = self.fields.get(field_id)
        if field is None:
            return False, f"no field #{field_id}"
        item = "electric_drill" if field.tier == "electric" else "burner_drill"
        if not self.economy.spend({item: n}):
            return False, f"no {item} in stock"
        field.drills += n
        self.log(f"Added {n} drill(s) to field #{field_id} (now {field.drills}).")
        return True, f"field #{field_id} drills now {field.drills}"

    # ---- snapshots --------------------------------------------------------
    def active_trains(self) -> int:
        return sum(1 for t in self.trains.values() if not t.stalled)

    def stats(self) -> dict:
        return {
            "time": self.time,
            "fields": len(self.fields),
            "trains": len(self.trains),
            "stalled_trains": sum(1 for t in self.trains.values() if t.stalled),
            "rail_tiles": int(self.net.total_rail_length()),
            "delivered": self.delivered_total,
            "discovered_patches": len(self.world.discovered_patches()),
            "claimable_patches": len(self.world.claimable_patches()),
            "coal": self.economy.inv.get("coal", 0),
        }
