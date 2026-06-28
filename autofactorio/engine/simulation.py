"""Simulation: the authoritative game state and tick loop.

Owns the world, economy, rail network, fields, trains, and scout. Exposes the
high-level build actions the director calls (these are the deterministic
"autopilot" that guarantees connectivity + collision-free routing) plus a
compact state snapshot for the LLM report and the HUD.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as _field

from .. import balance
from .animals import Animals
from .economy import Economy
from .mining import MiningField
from .rail import RailNetwork
from .research import Research
from .robots import Robots
from .trains import Train, Leg
from .world import World

LOAD_RATE = 800.0      # items/sec a train loads at a field stop
WAIT_IDLE = 6.0        # secs with no transfer before a train gives up waiting
LOAD_MAX_DWELL = 30.0  # secs a train will sit loading before leaving with a partial load
HOME = (0, 0)


@dataclass
class ConstructionJob:
    """A planned field/loop a robot must travel to and lay (track + drills) before
    the train can run."""
    id: int
    field_id: int
    x: float
    y: float
    edge_ids: list
    legs: list
    activates_field: bool


class Simulation:
    def __init__(self, config):
        self.config = config
        self.world = World(config.seed)
        self.economy = Economy()
        self.net = RailNetwork()
        self.research = Research()
        self.robots = Robots()
        self.robots.add(0.0, 0.0, explorer=True)     # robot #0 explores the map
        self.robots.add(0.0, 0.0, explorer=False)    # robot #1 builds/fights from the start
        self.animals = Animals(config.seed)
        self.fields: dict[int, MiningField] = {}
        self.trains: dict[int, Train] = {}
        self.jobs: dict[int, ConstructionJob] = {}
        self.kills = 0
        self._fid = 0
        self._tid = 0
        self._jid = 0
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

        for patch in self.robots.update(self, dt):
            self.log(f"Scout robot discovered a {patch.ore.replace('_', ' ')} patch "
                     f"(#{patch.id}) at ({patch.cx}, {patch.cy}).")
        self.animals.update(self, dt)

        for f in self.fields.values():
            f.update(dt, self.research.drill_mult)
            if f.patch.depleted and f.id not in self._depleted_announced:
                self._depleted_announced.add(f.id)
                self.log(f"Field #{f.id} ({f.patch.ore.replace('_', ' ')}) patch is exhausted.")
        self.economy.research_furnace_mult = self.research.furnace_mult
        self.economy.update(dt)

        # decide who holds the home-junction mutex this tick (granted by priority)
        self._arbitrate_junction()
        # snapshot car positions so trains can see each other and yield. Right of
        # way goes to higher-priority trains (loaded/returning beat empty/outbound)
        # and to whoever holds the junction; ties break by id so the order is
        # strict -> there is always a train that yields to no one -> no deadlock.
        positions = {tid: t.car_poses() for tid, t in self.trains.items()}
        holder = self.net.junction_occupant
        for tid in sorted(self.trains.keys(),
                          key=lambda i: self.trains[i].traffic_priority()):
            t = self.trains[tid]
            if t.holds_junction:
                obstacles = []                            # committed through the throat
            else:
                mykey = t.traffic_priority()
                obstacles = [(x, y)
                             for otid, ot in self.trains.items()
                             if otid != tid
                             and (ot.traffic_priority() < mykey or otid == holder)
                             for (x, y, _a, _k) in positions[otid]]
            t.update_movement(dt, self.net, obstacles)
            if t.state == "waiting":
                self._service_station(t, dt)
        self.net.update_signals()
        self._reveal_along_trains()
        self._crush_animals()
        self._update_decommission()

    # ---- robots / animals -------------------------------------------------
    @property
    def scout(self):
        """The explorer robot (camera-follow + minimap still call this 'scout')."""
        return self.robots.explorer()

    def can_build_robot(self) -> bool:
        # a robot must be assembled in stock (a "factory") and under the cap
        return (self.economy.assemblers >= 1
                and len(self.robots) < self.research.max_robots
                and self.economy.inv.get("robot", 0) >= 1)

    def can_replace_robot(self) -> bool:
        """Animals only retaliate when losing a robot is recoverable - a spare
        exists, or the base has one assembled and ready."""
        return len(self.robots) >= 2 or self.can_build_robot()

    def build_robot(self) -> tuple[bool, str]:
        if len(self.robots) >= self.research.max_robots:
            return False, f"robot cap reached ({self.research.max_robots})"
        if self.economy.assemblers < 1:
            return False, "no factory to deploy a robot"
        if not self.economy.spend({"robot": 1}):
            return False, "no robot in stock yet"
        r = self.robots.add(0.0, 0.0, explorer=False)
        self.log(f"Deployed robot #{r.id} ({len(self.robots)}/{self.research.max_robots}).")
        return True, f"robot #{r.id} deployed"

    def _crush_animals(self) -> None:
        rng2 = balance.TRAIN_CRUSH_RANGE ** 2
        for t in self.trains.values():
            if t.state != "moving":
                continue
            poses = t.car_poses()
            if not poses:
                continue
            for a in self.animals.near(poses[0][0], poses[0][1], balance.TRAIN_CRUSH_RANGE + balance.ENTITY_LEN):
                for (cx, cy, _ang, _kind) in poses:
                    if (a.x - cx) ** 2 + (a.y - cy) ** 2 <= rng2:
                        self.animals.crush(a.id)
                        self.kills += 1
                        t.hp = max(0.0, t.hp - balance.TRAIN_CRUSH_DAMAGE)
                        self.log(f"Train #{t.id} crushed wildlife (-{int(balance.TRAIN_CRUSH_DAMAGE)} hp).")
                        break

    def _arbitrate_junction(self) -> None:
        """Interlock the home junction (the origin throat every loop crosses):
        release it once the current holder's tail has cleared, then grant it to the
        highest-priority train approaching it. At most one train is ever inside, so
        departing trains never collide or block the crossing - the rest queue at the
        chain signal just outside until it is their turn."""
        net = self.net
        occ = net.junction_occupant
        if occ is not None:
            t = self.trains.get(occ)
            if t is None or t.clear_of_junction():
                net.junction_occupant = None
                if t is not None:
                    t.holds_junction = False
                occ = None
        if occ is not None:
            return                                        # still in use; others wait
        requesters = [t for t in self.trains.values() if t.wants_junction()]
        if not requesters:
            return
        winner = min(requesters, key=lambda t: t.traffic_priority())
        net.junction_occupant = winner.id
        winner.holds_junction = True

    def _reveal_along_trains(self) -> None:
        """Running trains chart their route: each car clears fog around it, so the
        rail corridors out to the fields stay lit and a train can stumble onto a
        new patch the scout hasn't reached yet."""
        radius = balance.TRAIN_REVEAL_RADIUS
        for t in self.trains.values():
            if t.state != "moving":
                continue
            for (x, y, _ang, _kind) in t.car_poses():
                for patch in self.world.reveal(x, y, radius):
                    self.log(f"Train #{t.id} sighted a {patch.ore.replace('_', ' ')} "
                             f"patch (#{patch.id}) at ({patch.cx}, {patch.cy}).")

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
            rate = balance.BASE_UNLOAD_RATE * self.research.unload_mult
            budget = max(1, int(rate * dt))
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
            # a recalled train that has reached the home (unload) stop empty goes
            # into storage instead of looping back out
            if train.recall and st.is_home and train.cargo_total() == 0:
                self._store_train(train)
            else:
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
        rails_needed = int((int(dist * 1.15) + 10) * self.research.rail_discount)
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
        field.edge_ids = list(out_e) + list(ret_e)
        field.station_ids = [load_st.id, unload_st.id]
        field.rail_used = rails_needed
        field.state = "constructing"                 # a robot must lay it before it runs
        for eid in field.edge_ids:                    # ghost the planned track
            self.net.edges[eid].built = False
        load_st.field_id = fid
        load_st.name = f"{patch.ore}-{fid}-load"
        unload_st.name = f"home-{fid}-unload"
        patch.claimed = True
        self.fields[fid] = field

        legs = [Leg(out_e, load_st.id, ("full_cargo",)),
                Leg(ret_e, unload_st.id, ("empty_cargo",))]
        self._new_job(fid, patch.cx, patch.cy, list(field.edge_ids), legs, activates_field=True)
        self.economy.spend(costs)
        self._deplete_nearer_fields(fid, math.dist(HOME, (patch.cx, patch.cy)))
        self.log(f"Field #{fid} planned on {patch.ore.replace('_', ' ')} patch #{patch_id}; "
                 f"a robot will lay {rails_needed} rail and {field.drills} drills.")
        return True, f"field #{fid} planned on patch #{patch_id} ({patch.ore})"

    # ---- construction jobs (robots lay the track + drills) ----------------
    def _new_job(self, field_id, x, y, edge_ids, legs, activates_field):
        jid = self._jid
        self._jid += 1
        self.jobs[jid] = ConstructionJob(jid, field_id, float(x), float(y),
                                         list(edge_ids), legs, activates_field)
        return jid

    def complete_job(self, job) -> None:
        """A robot reached the build site: solidify the track and dispatch the train."""
        for eid in job.edge_ids:
            e = self.net.edges.get(eid)
            if e is not None:
                e.built = True
        tid = self._tid
        self._tid += 1
        self.trains[tid] = Train(tid, job.legs, balance.DEFAULT_WAGONS, self.net, self.research)
        field = self.fields.get(job.field_id)
        if job.activates_field and field is not None:
            field.state = "active"
        self.jobs.pop(job.id, None)
        self.log(f"Robot laid the track for field #{job.field_id}; train #{tid} dispatched.")

    def _deplete_nearer_fields(self, new_fid: int, new_dist: float) -> None:
        """Claiming a farther field accelerates depletion of the nearer ones in
        proportion to how much closer they are - the frontier moves outward and
        old close fields run dry (then their track is reclaimed on abandon)."""
        if new_dist <= 0:
            return
        for other in self.fields.values():
            if other.id == new_fid:
                continue
            od = math.dist(HOME, (other.patch.cx, other.patch.cy))
            if od < new_dist:
                frac = balance.EXPANSION_DEPLETE_K * (1.0 - od / new_dist)
                other.patch.reserve = max(0, int(other.patch.reserve * (1.0 - frac)))

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
        field.edge_ids += list(out_e) + list(ret_e)      # reclaim this loop too
        field.station_ids += [load_st.id, unload_st.id]
        field.rail_used += rails_needed
        for eid in list(out_e) + list(ret_e):            # ghost until a robot lays it
            self.net.edges[eid].built = False
        legs = [Leg(out_e, load_st.id, ("full_cargo",)),
                Leg(ret_e, unload_st.id, ("empty_cargo",))]
        self._new_job(field_id, patch.cx, patch.cy, list(out_e) + list(ret_e),
                      legs, activates_field=False)
        self.economy.spend(costs)
        self.log(f"Second loop for field #{field_id} planned; a robot will lay the track.")
        return True, f"second loop for field #{field_id} planned"

    def abandon_field(self, field_id: int) -> tuple[bool, str]:
        """Begin decommissioning a depleted field. This does NOT instantly remove
        anything: the field's trains are recalled to finish their run, drive home,
        and go into storage; only once they are all stored does a robot get sent
        to tear up the track + drills and haul the materials back to base."""
        field = self.fields.get(field_id)
        if field is None:
            return False, f"no field #{field_id}"
        if field.state != "active":
            return True, f"field #{field_id} already decommissioning"
        if not field.patch.depleted:
            return False, f"field #{field_id} still has ore; not abandoning"
        field.state = "recalling"
        n = 0
        for t in self.trains.values():
            if self._train_field(t) == field_id:
                t.recall = True
                n += 1
        self.log(f"Field #{field_id} depleted: recalling {n} train(s) to storage "
                 f"before tearing up the track.")
        return True, f"decommissioning field #{field_id}"

    def _train_field(self, train: Train) -> int | None:
        st = self.net.stations.get(train.legs[0].station_id)
        return st.field_id if st is not None else None

    def _store_train(self, train: Train) -> None:
        for bid in list(train.locked):
            blk = self.net.blocks.get(bid)
            if blk is not None and blk.occupant == train.id:
                blk.occupant = None
        self.economy.add("locomotive", 1)
        self.economy.add("cargo_wagon", train.wagons)
        self.trains.pop(train.id, None)
        self.log(f"Train #{train.id} returned home and went into storage "
                 f"(+1 loco, +{train.wagons} wagons).")

    def _update_decommission(self) -> None:
        """Advance fields through recalling -> dismantling once their trains are
        all home/stored (robots then handle the actual teardown)."""
        for field in self.fields.values():
            if field.state == "recalling":
                if not any(self._train_field(t) == field.id for t in self.trains.values()):
                    field.state = "dismantling"
                    self.log(f"Field #{field.id}: all trains stored; dispatching a robot "
                             f"to dismantle the track.")

    def teardown_field_track(self, field) -> dict:
        """Called by a robot that has reached a decommissioned field: remove its
        track from the network and return the materials it should haul home
        (drills + stops fully recovered, rail partially)."""
        self.net.remove_edges(field.edge_ids)
        for sid in field.station_ids:
            self.net.remove_station(sid)
        drill_item = "electric_drill" if field.tier == "electric" else "burner_drill"
        materials = {
            "rail": int(field.rail_used * balance.RECLAIM_REFUND),
            "train_stop": len(field.station_ids),
            drill_item: field.drills,
        }
        self.fields.pop(field.id, None)
        self._depleted_announced.discard(field.id)
        return materials

    def research_next(self) -> tuple[bool, str]:
        """Research the next tech if its cost is in stock; applies the effect and
        propagates the new tuning to existing trains and the economy."""
        tech = self.research.next_tech()
        if tech is None:
            return False, "all techs researched"
        if not self.economy.have(tech["cost"]):
            missing = {k: v for k, v in tech["cost"].items() if self.economy.inv.get(k, 0) < v}
            return False, f"insufficient for research '{tech['name']}': need {missing}"
        self.economy.spend(tech["cost"])
        self.research.apply(tech)
        # propagate to existing trains
        for t in self.trains.values():
            t.max_speed = self.research.train_speed
            t.accel = self.research.train_accel
            t.capacity = t.wagons * self.research.wagon_capacity
        self.economy.research_furnace_mult = self.research.furnace_mult
        self.log(f"Researched '{tech['name']}' (L{self.research.level}): {tech['desc']}.")
        return True, f"researched {tech['name']}"

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

    # ---- persistence ------------------------------------------------------
    def save(self, path: str) -> tuple[bool, str]:
        from .persistence import save_game
        try:
            save_game(self, path)
            self.log(f"Game saved to {path}.")
            return True, path
        except Exception as e:                 # never let a save crash the game
            self.log(f"Save failed: {e}")
            return False, str(e)

    def load(self, path: str) -> tuple[bool, str]:
        from .persistence import load_into
        try:
            load_into(self, path)
            self.log(f"Game loaded from {path}.")
            return True, path
        except Exception as e:
            self.log(f"Load failed: {e}")
            return False, str(e)

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
            "tech_level": self.research.level,
            "robots": len(self.robots),
            "max_robots": self.research.max_robots,
            "animals": len(self.animals.list),
            "kills": self.kills,
            "damaged_trains": sum(1 for t in self.trains.values() if t.hp < t.max_hp - 0.5),
        }
