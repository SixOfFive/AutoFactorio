"""Robots: the explorer that reveals fog and hunts animals, plus helpers built
up to the research cap (max 3). Each tick the fleet is assigned by priority:

  1. repair a damaged train   (highest)
  2. gather emergency fuel     (only when home coal is critically low - slow)
  3. hunt nearby animals
  4. explore the frontier      (the explorer's default; pushes the fog back)

The explorer (robot 0) also kills animals it passes while exploring.
"""

from __future__ import annotations

import math

from .. import balance


class Robot:
    def __init__(self, rid: int, x: float, y: float, explorer: bool = False):
        self.id = rid
        self.x = x
        self.y = y
        self.heading = 0.0
        self.hp = balance.ROBOT_HP
        self.explorer = explorer
        self.task = "explore"
        self.target = None
        self.attack_cd = 0.0
        self.carry_coal = 0.0
        self.fuel_phase: str | None = None       # 'to_coal' | 'return'
        self.dismantle_phase: str | None = None  # 'to_field' | 'to_home'
        self.carry_reclaim: dict = {}            # materials hauled back from a torn-up field
        # spiral-explore state
        self.angle = 0.7
        self.radius = float(balance.PATCH_MIN_RING)
        self.tx, self.ty = self._spiral_target()

    @property
    def pos(self) -> tuple[float, float]:
        return self.x, self.y

    def _spiral_target(self) -> tuple[float, float]:
        return math.cos(self.angle) * self.radius, math.sin(self.angle) * self.radius

    def _advance_spiral(self) -> None:
        max_r = balance.MAP_RADIUS - balance.SCOUT_REVEAL_RADIUS - 2
        dtheta = max(0.25, balance.SCOUT_REVEAL_RADIUS / max(self.radius, 1.0))
        self.angle += dtheta
        if self.radius < max_r:
            self.radius = min(max_r, self.radius + balance.SCOUT_REVEAL_RADIUS * dtheta / (2 * math.pi) * 6)
        else:
            # finished an outward spiral: head back near home and spiral out again
            # on a rotated arm, so repeated passes fill in any remaining fog gaps.
            self.radius = float(balance.SCOUT_REVEAL_RADIUS)
            self.angle += 2.39996                      # golden-angle offset for fresh coverage
        self.tx, self.ty = self._spiral_target()

    def move_toward(self, tx: float, ty: float, speed: float, dt: float) -> float:
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        if d > 1e-6:
            step = min(d, speed * dt)
            self.x += dx / d * step
            self.y += dy / d * step
            self.heading = math.degrees(math.atan2(dy, dx))
        return d


class Robots:
    def __init__(self) -> None:
        self.list: dict[int, Robot] = {}
        self._rid = 0

    # dict-like helpers (animals.py reads .get/.values)
    def add(self, x: float = 0.0, y: float = 0.0, explorer: bool = False) -> Robot:
        r = Robot(self._rid, x, y, explorer)
        self.list[self._rid] = r
        self._rid += 1
        return r

    def get(self, rid):
        return self.list.get(rid)

    def values(self):
        return self.list.values()

    def __len__(self):
        return len(self.list)

    def __iter__(self):
        return iter(self.list.values())

    def explorer(self) -> Robot:
        for r in self.list.values():
            if r.explorer:
                return r
        return next(iter(self.list.values()))

    # ---- per-tick update --------------------------------------------------
    def update(self, sim, dt: float) -> list:
        discovered = []
        self._assign(sim)
        for r in list(self.list.values()):
            if r.hp <= 0:
                self._destroy(sim, r)
                continue
            if r.attack_cd > 0:
                r.attack_cd -= dt
            if r.task == "repair":
                self._do_repair(sim, r, dt)
            elif r.task == "construct":
                self._do_construct(sim, r, dt)
            elif r.task == "dismantle":
                self._do_dismantle(sim, r, dt)
            elif r.task == "fuel":
                self._do_fuel(sim, r, dt)
            elif r.task == "hunt":
                self._do_hunt(sim, r, dt)
            else:
                self._do_explore(sim, r, dt)
            # slow self-repair when no animal is in melee range
            if r.hp < balance.ROBOT_HP and sim.animals.nearest(r.x, r.y, balance.ROBOT_ATTACK_RANGE + 1.0) is None:
                r.hp = min(balance.ROBOT_HP, r.hp + balance.ROBOT_REGEN * dt)
            # every robot clears a little fog around itself
            radius = balance.SCOUT_REVEAL_RADIUS if r.explorer else balance.SCOUT_REVEAL_RADIUS * 0.6
            discovered += sim.world.reveal(r.x, r.y, radius)
        return discovered

    # ---- assignment -------------------------------------------------------
    def _assign(self, sim) -> None:
        # keep robots that are mid-job (constructing / dismantling) on task
        busy = set()
        for r in self.list.values():
            keep = ((r.task == "construct" and r.target in sim.jobs) or
                    (r.task == "dismantle" and r.dismantle_phase is not None))
            if keep:
                busy.add(r.id)
            else:
                r.task = None
        covered_jobs = {self.list[rid].target for rid in busy if self.list[rid].task == "construct"}
        covered_fields = {self.list[rid].target for rid in busy if self.list[rid].task == "dismantle"}
        free = sorted((r for r in self.list.values() if r.id not in busy),
                      key=lambda r: (r.explorer, r.id))    # explorer last
        # 1. repair the most-damaged trains
        damaged = sorted((t for t in sim.trains.values() if t.hp < t.max_hp - 0.5),
                         key=lambda t: t.hp)
        for t in damaged:
            if not free:
                break
            loco = _train_head(t)
            if loco is None:
                continue
            r = min(free, key=lambda r: (r.x - loco[0]) ** 2 + (r.y - loco[1]) ** 2)
            r.task = "repair"
            r.target = t.id
            free.remove(r)
        # 2. build planned fields/loops (lay track + drills)
        for job in sim.jobs.values():
            if job.id in covered_jobs:
                continue
            if not free:
                break
            r = min(free, key=lambda r: (r.x - job.x) ** 2 + (r.y - job.y) ** 2)
            r.task = "construct"
            r.target = job.id
            covered_jobs.add(job.id)
            free.remove(r)
        # 3. dismantle fields whose trains are already stored (track tear-down)
        for f in sim.fields.values():
            if getattr(f, "state", "active") != "dismantling" or f.id in covered_fields:
                continue
            if not free:
                break
            r = min(free, key=lambda r: (r.x - f.patch.cx) ** 2 + (r.y - f.patch.cy) ** 2)
            r.task = "dismantle"
            r.target = f.id
            r.dismantle_phase = "to_field"
            covered_fields.add(f.id)
            free.remove(r)
        # 4. emergency fuel (one robot) when coal is critically low
        if sim.economy.inv.get("coal", 0) < balance.FUEL_CRITICAL and free:
            r = free.pop(0)
            r.task = "fuel"
        # 5 & 6. remaining robots hunt nearby animals, else explore
        for r in free:
            target = None if r.explorer else sim.animals.nearest(r.x, r.y, balance.ROBOT_HUNT_RADIUS)
            if target is not None:
                r.task = "hunt"
                r.target = target.id
            else:
                r.task = "explore"

    # ---- task handlers ----------------------------------------------------
    def _attack(self, sim, r: Robot, animal) -> None:
        if r.attack_cd > 0:
            return
        r.attack_cd = balance.ROBOT_ATTACK_COOLDOWN
        died = sim.animals.hit(animal.id, balance.ROBOT_ATTACK, r.id,
                               retaliate=sim.can_replace_robot())
        if died:
            sim.kills = getattr(sim, "kills", 0) + 1

    def _do_hunt(self, sim, r: Robot, dt: float) -> None:
        a = sim.animals.list.get(r.target) if r.target is not None else None
        if a is None:
            a = sim.animals.nearest(r.x, r.y, balance.ROBOT_HUNT_RADIUS)
            r.target = a.id if a else None
        if a is None:
            self._do_explore(sim, r, dt)
            return
        d = r.move_toward(a.x, a.y, balance.ROBOT_SPEED, dt)
        if d <= balance.ROBOT_ATTACK_RANGE:
            self._attack(sim, r, a)

    def _do_explore(self, sim, r: Robot, dt: float) -> None:
        # opportunistically swat an animal in reach
        a = sim.animals.nearest(r.x, r.y, balance.ROBOT_ATTACK_RANGE + 0.5)
        if a is not None:
            self._attack(sim, r, a)
        d = r.move_toward(r.tx, r.ty, balance.ROBOT_SPEED if not r.explorer else balance.SCOUT_SPEED, dt)
        if d < 1.0:
            r._advance_spiral()

    def _do_repair(self, sim, r: Robot, dt: float) -> None:
        t = sim.trains.get(r.target) if r.target is not None else None
        if t is None or t.hp >= t.max_hp:
            r.task = "explore"
            return
        head = _train_head(t)
        if head is None:
            return
        d = r.move_toward(head[0], head[1], balance.ROBOT_SPEED, dt)
        if d <= balance.ROBOT_ATTACK_RANGE + 1.0:
            t.hp = min(t.max_hp, t.hp + balance.ROBOT_REPAIR_RATE * dt)

    def _do_construct(self, sim, r: Robot, dt: float) -> None:
        # travel to a planned field/loop and lay its track + drills, then the train
        # gets dispatched.
        job = sim.jobs.get(r.target)
        if job is None:
            r.task = "explore"
            r.target = None
            return
        d = r.move_toward(job.x, job.y, balance.ROBOT_SPEED, dt)
        if d <= 2.5:
            sim.complete_job(job)
            r.task = "explore"
            r.target = None

    def _do_dismantle(self, sim, r: Robot, dt: float) -> None:
        # travel out to a decommissioned field, tear up its track + drills, and
        # haul the materials back to base for reuse.
        if r.dismantle_phase is None:
            r.dismantle_phase = "to_field"
        if r.dismantle_phase == "to_field":
            field = sim.fields.get(r.target)
            if field is None:                       # already gone
                r.dismantle_phase = None
                r.task = "explore"
                return
            d = r.move_toward(field.patch.cx, field.patch.cy, balance.ROBOT_SPEED, dt)
            if d <= 2.5:
                r.carry_reclaim = sim.teardown_field_track(field)
                r.dismantle_phase = "to_home"
                sim.log(f"Robot #{r.id} tore up field #{r.target}'s track; hauling salvage home.")
        elif r.dismantle_phase == "to_home":
            d = r.move_toward(0.0, 0.0, balance.ROBOT_SPEED, dt)
            if d < 2.5:
                # deposit only what storage can hold; keep the rest and retry next
                # tick (back-pressure) so finite storage never silently eats salvage.
                deposited = {}
                for k in list(r.carry_reclaim.keys()):
                    want = int(r.carry_reclaim[k])
                    if want <= 0:
                        r.carry_reclaim.pop(k, None)
                        continue
                    got = sim.economy.add(k, want)
                    if got:
                        deposited[k] = got
                    rem = want - got
                    if rem > 0:
                        r.carry_reclaim[k] = rem
                    else:
                        r.carry_reclaim.pop(k, None)
                if deposited:
                    sim.log(f"Robot #{r.id} returned salvage to base for reuse: {deposited}.")
                if not r.carry_reclaim:          # all stored -> done
                    r.dismantle_phase = None
                    r.target = None
                    r.task = "explore"
                # else: storage full; wait at base and keep depositing as room frees

    def _do_fuel(self, sim, r: Robot, dt: float) -> None:
        # slow last-resort coal run: go to the nearest known coal patch, fill up,
        # bring it home, deposit. Becomes priority only while coal is critical.
        if r.fuel_phase is None:
            r.fuel_phase = "to_coal"
        if r.fuel_phase == "return" or r.carry_coal >= balance.ROBOT_FUEL_CARRY:
            r.fuel_phase = "return"
            d = r.move_toward(0, 0, balance.ROBOT_SPEED, dt)
            if d < 2.5:
                sim.economy.add("coal", int(r.carry_coal))
                if r.carry_coal:
                    sim.log(f"Robot #{r.id} delivered {int(r.carry_coal)} emergency coal.")
                r.carry_coal = 0.0
                r.fuel_phase = None
                r.task = "explore"
            return
        # to_coal: find nearest discovered, non-depleted coal patch
        patch = _nearest_coal(sim, r.x, r.y)
        if patch is None:                          # nothing to harvest; give up
            r.task = "explore"
            r.fuel_phase = None
            return
        d = r.move_toward(patch.cx, patch.cy, balance.ROBOT_SPEED, dt)
        if d <= 2.5:
            got = min(balance.ROBOT_FUEL_GATHER_RATE * dt, patch.reserve)
            patch.mine(got)
            r.carry_coal += got

    def _destroy(self, sim, r: Robot) -> None:
        self.list.pop(r.id, None)
        sim.log(f"Robot #{r.id} was destroyed by wildlife.")


def _train_head(t):
    poses = t.car_poses()
    return (poses[0][0], poses[0][1]) if poses else None


def _nearest_coal(sim, x, y):
    best, best_d = None, 1e18
    for p in sim.world.patches:
        if p.ore == "coal" and p.discovered and not p.depleted:
            d = (p.cx - x) ** 2 + (p.cy - y) ** 2
            if d < best_d:
                best, best_d = p, d
    return best
