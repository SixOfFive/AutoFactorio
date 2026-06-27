"""Wildlife: herds that wander, can spawn out in the fog, and only fight back
when provoked AND the base could replace the robot they'd kill.

Animals never attack buildings. They take damage from robots (hunting) and from
trains (crushing). When a robot attacks one and the colony can afford to lose the
robot (a spare exists or another can be built), the victim's herdmates turn and
chase the robot; otherwise they flee.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .. import balance


@dataclass
class Animal:
    id: int
    x: float
    y: float
    herd: int
    hp: float = balance.ANIMAL_HP
    state: str = "wander"          # wander | attack | flee
    target_robot: int | None = None


class Animals:
    def __init__(self, seed: int):
        self.rng = random.Random(seed ^ 0xA17A1)
        self.list: dict[int, Animal] = {}
        self.herd_centers: dict[int, list[float]] = {}
        self._aid = 0
        self._hid = 0
        self._spawn_timer = balance.HERD_SPAWN_INTERVAL * 0.4

    # ---- spawning ---------------------------------------------------------
    def _fog_spawn_point(self, world) -> tuple[int, int] | None:
        R = world.radius
        for _ in range(50):
            tx = self.rng.randint(-R + 4, R - 4)
            ty = self.rng.randint(-R + 4, R - 4)
            if tx * tx + ty * ty < 30 * 30:        # not on top of base
                continue
            if not world.is_explored(tx, ty):       # spawn hidden in the fog
                return tx, ty
        return None

    def _spawn_herd(self, world) -> None:
        pt = self._fog_spawn_point(world)
        if pt is None:
            return
        hid = self._hid
        self._hid += 1
        self.herd_centers[hid] = [float(pt[0]), float(pt[1])]
        n = self.rng.randint(*balance.HERD_SIZE)
        for _ in range(n):
            if len(self.list) >= balance.ANIMAL_MAX:
                break
            ax = pt[0] + self.rng.uniform(-3, 3)
            ay = pt[1] + self.rng.uniform(-3, 3)
            self.list[self._aid] = Animal(self._aid, ax, ay, hid)
            self._aid += 1

    # ---- combat hooks (called by robots / trains) -------------------------
    def hit(self, animal_id: int, damage: float, by_robot: int | None,
            retaliate: bool) -> bool:
        """Apply damage; on survival, either rally the herd against `by_robot`
        (retaliate=True) or make them flee. Returns True if the animal died."""
        a = self.list.get(animal_id)
        if a is None:
            return False
        a.hp -= damage
        if a.hp <= 0:
            self._remove(animal_id)
            return True
        if by_robot is not None:
            new_state = "attack" if retaliate else "flee"
            for other in self.list.values():
                if other.herd == a.herd and math.dist((other.x, other.y), (a.x, a.y)) <= balance.ANIMAL_AGGRO_RANGE:
                    other.state = new_state
                    other.target_robot = by_robot if retaliate else None
        return False

    def crush(self, animal_id: int) -> None:
        self._remove(animal_id)

    def _remove(self, animal_id: int) -> None:
        a = self.list.pop(animal_id, None)
        if a and not any(o.herd == a.herd for o in self.list.values()):
            self.herd_centers.pop(a.herd, None)

    def near(self, x: float, y: float, radius: float) -> list[Animal]:
        r2 = radius * radius
        return [a for a in self.list.values()
                if (a.x - x) ** 2 + (a.y - y) ** 2 <= r2]

    def nearest(self, x: float, y: float, radius: float) -> Animal | None:
        best, best_d = None, radius * radius
        for a in self.list.values():
            d = (a.x - x) ** 2 + (a.y - y) ** 2
            if d <= best_d:
                best, best_d = a, d
        return best

    # ---- per-tick update --------------------------------------------------
    def update(self, sim, dt: float) -> None:
        self._spawn_timer -= dt
        if self._spawn_timer <= 0:
            self._spawn_timer = balance.HERD_SPAWN_INTERVAL
            self._spawn_herd(sim.world)

        # drift herd centers gently
        for c in self.herd_centers.values():
            c[0] += self.rng.uniform(-1, 1) * balance.HERD_DRIFT * dt
            c[1] += self.rng.uniform(-1, 1) * balance.HERD_DRIFT * dt

        robots = sim.robots
        for a in list(self.list.values()):
            if a.state == "attack":
                self._do_attack(a, robots, dt)
            elif a.state == "flee":
                self._do_flee(a, robots, dt)
            else:
                self._do_wander(a, dt)

    def _do_wander(self, a: Animal, dt: float) -> None:
        c = self.herd_centers.get(a.herd, [a.x, a.y])
        dx, dy = c[0] - a.x, c[1] - a.y
        d = math.hypot(dx, dy) or 1.0
        if d > balance.HERD_WANDER_RADIUS:        # drift back toward the herd
            a.x += dx / d * balance.ANIMAL_SPEED * dt
            a.y += dy / d * balance.ANIMAL_SPEED * dt
        else:                                      # mill about
            a.x += self.rng.uniform(-1, 1) * balance.ANIMAL_SPEED * dt
            a.y += self.rng.uniform(-1, 1) * balance.ANIMAL_SPEED * dt

    def _do_attack(self, a: Animal, robots, dt: float) -> None:
        r = robots.get(a.target_robot) if a.target_robot is not None else None
        if r is None:                              # target gone -> calm down
            a.state = "wander"
            a.target_robot = None
            return
        dx, dy = r.x - a.x, r.y - a.y
        d = math.hypot(dx, dy) or 1.0
        if d <= balance.ANIMAL_ATTACK_RANGE:
            r.hp -= balance.ANIMAL_DPS * dt
        else:
            a.x += dx / d * balance.ANIMAL_CHASE_SPEED * dt
            a.y += dy / d * balance.ANIMAL_CHASE_SPEED * dt

    def _do_flee(self, a: Animal, robots, dt: float) -> None:
        nearest = None
        best = 1e18
        for r in robots.values():
            dd = (r.x - a.x) ** 2 + (r.y - a.y) ** 2
            if dd < best:
                best, nearest = dd, r
        if nearest is None or best > 30 * 30:
            a.state = "wander"
            return
        dx, dy = a.x - nearest.x, a.y - nearest.y
        d = math.hypot(dx, dy) or 1.0
        a.x += dx / d * balance.ANIMAL_CHASE_SPEED * dt
        a.y += dy / d * balance.ANIMAL_CHASE_SPEED * dt
