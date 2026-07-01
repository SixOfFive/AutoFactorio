"""Trains: composition, movement along leg polylines, block-mutex locking,
fuel, cargo, and a looping schedule of legs.

A Train owns its physics/movement and block reservation. Economy interactions
(loading ore, unloading at home, refueling) are driven by the Simulation when a
train is parked, to avoid an engine<->sim import cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import balance
from .rail import RailNetwork


@dataclass
class Leg:
    edges: list[int]
    station_id: int
    wait: tuple                      # ('full_cargo',) | ('empty_cargo',) | ('time', secs)


class Train:
    def __init__(self, tid: int, legs: list[Leg], wagons: int, net: RailNetwork, research=None):
        self.id = tid
        self.legs = legs
        self.wagons = wagons
        self.variant = tid % 4           # which loco/wagon sprite set to draw
        # per-train tuning (lifted by research); fall back to base balance numbers
        self.max_speed = research.train_speed if research else balance.TRAIN_MAX_SPEED
        self.accel = research.train_accel if research else balance.TRAIN_ACCEL
        cap_each = research.wagon_capacity if research else balance.CARGO_WAGON_CAPACITY
        self.capacity = wagons * cap_each
        self.max_hp = balance.TRAIN_HP
        self.hp = balance.TRAIN_HP
        self.cargo: dict[str, int] = {}
        self.fuel_seconds = balance.LOCO_START_FUEL * balance.COAL_BURN_SECONDS
        self.speed = 0.0
        self.state = "moving"            # 'moving' | 'waiting'
        self.cur_leg = 0
        self.wait_timer = 0.0
        self.idle_timer = 0.0            # seconds since last cargo transfer
        self.stalled = False             # out of fuel mid-track
        self.waiting_for_train = False   # yielding to another train ahead
        self.recall = False              # field decommissioned: return home and store
        self.trunk_id = -1               # the corridor this train serves (its milk-run of fields)
        self.locked: set[int] = set()
        self.holds_junction = False      # currently granted this train's home-throat mutex
        self.blocked_time = 0.0          # seconds held still by traffic (anti-deadlock)
        # this train's home throat (its trunk's turnaround) - set by the Simulation
        # once the train is tied to a field/trunk; falls back to the legacy origin one
        self.throat_center: tuple[float, float] | None = None
        self.throat_radius: float = 0.0
        self.throat_trunk: int = -1
        # arc-length span of this leg that lies inside the home throat (or None)
        self.junc_enter: float | None = None
        self.junc_exit: float | None = None
        # current-leg cached geometry
        self._pts: list[tuple[float, float]] = []
        self._cum: list[float] = []
        self._intervals: list[tuple[float, float, int]] = []  # (start, end, block_id)
        self.leg_len = 0.0
        self.head_s = 0.0
        # previous leg's geometry so trailing cars keep flowing across the boundary
        self._prev_pts: list[tuple[float, float]] = []
        self._prev_cum: list[float] = []
        self._prev_intervals: list[tuple[float, float, int]] = []
        self._prev_len = 0.0
        self.begin_leg(net, 0)

    # ---- cargo ------------------------------------------------------------
    def cargo_total(self) -> int:
        return sum(self.cargo.values())

    def cargo_free(self) -> int:
        return self.capacity - self.cargo_total()

    # ---- leg geometry -----------------------------------------------------
    def begin_leg(self, net: RailNetwork, idx: int) -> None:
        # remember the leg we're leaving so the wagons can keep trailing onto it
        if self._pts:
            self._prev_pts = self._pts
            self._prev_cum = self._cum
            self._prev_intervals = self._intervals
            self._prev_len = self.leg_len
        self.cur_leg = idx
        leg = self.legs[idx]
        pts: list[tuple[float, float]] = []
        intervals: list[tuple[float, float, int]] = []
        acc = 0.0
        for eid in leg.edges:
            e = net.edges[eid]
            if not pts:
                pts.append(e.points[0])
            for p in e.points[1:]:
                pts.append(p)
            intervals.append((acc, acc + e.length, e.block_id))
            acc += e.length
        if not pts:                      # degenerate leg (shouldn't happen)
            pts = [net.node_pos(net.stations[leg.station_id].node_id)]
        self._pts = pts
        self._cum = _cumulative(pts)
        self._intervals = intervals
        self.leg_len = self._cum[-1] if self._cum else 0.0
        self.head_s = 0.0
        self.speed = 0.0
        self.state = "moving"
        # find where (if at all) this leg crosses this train's home throat
        center = self.throat_center if self.throat_center is not None else net.junction_center
        radius = self.throat_radius if self.throat_center is not None else net.junction_radius
        ji = _junction_interval(self._pts, self._cum, center, radius)
        self.junc_enter, self.junc_exit = ji if ji else (None, None)

    def set_throat(self, center, radius, trunk_id: int, net: RailNetwork) -> None:
        """Bind this train to its trunk's home throat and recompute where the current
        leg crosses it (called when the train is created/loaded for a field)."""
        self.throat_center = (float(center[0]), float(center[1]))
        self.throat_radius = float(radius)
        self.throat_trunk = trunk_id
        ji = _junction_interval(self._pts, self._cum, self.throat_center, self.throat_radius)
        self.junc_enter, self.junc_exit = ji if ji else (None, None)

    @staticmethod
    def _block_in(dist: float, intervals) -> int | None:
        for s, e, bid in intervals:
            if s <= dist <= e:
                return bid
        return None

    def _block_at(self, dist: float) -> int | None:
        return self._block_in(dist, self._intervals)

    def _block_start(self, bid: int) -> float:
        for s, _, b in self._intervals:
            if b == bid:
                return s
        return 0.0

    def _body_blocks(self) -> set[int]:
        lo = self.head_s - balance.MAX_TRAIN_LEN
        ids: set[int] = set()
        d = max(0.0, lo)
        while d < self.head_s:
            b = self._block_at(d)
            if b is not None:
                ids.add(b)
            d += 1.0
        b = self._block_at(self.head_s)
        if b is not None:
            ids.add(b)
        # RESERVE-AHEAD: also claim the block a short distance in front of the head.
        # This is what interlocks merges - a train grabs the block it is about to
        # enter while still MERGE_CLEAR tiles short of it, so a train converging from
        # another track sees it taken and stops back instead of both nosing into the
        # join and freezing each other.
        b = self._block_at(min(self.leg_len, self.head_s + balance.MERGE_CLEAR))
        if b is not None:
            ids.add(b)
        # the tail can still trail onto the PREVIOUS leg (cars span the boundary just
        # after departing a stop); reserve those blocks too, so a following train can't
        # drive into our wagons across the leg boundary (a real collision otherwise).
        if lo < 0 and self._prev_intervals and self._prev_len > 0:
            d = max(0.0, self._prev_len + lo)
            while d <= self._prev_len:
                b = self._block_in(d, self._prev_intervals)
                if b is not None:
                    ids.add(b)
                d += 1.0
        return ids

    # ---- chain-signal path reservation ------------------------------------
    def _chain_run(self, net: RailNetwork, ki: int) -> list[int]:
        """From interval index `ki` (a CHAIN block), the contiguous run of chain blocks on
        this leg PLUS the first plain block beyond (the safe exit). This is the atomic path
        a train must reserve to pass a chain signal - it never stops inside a junction."""
        run: list[int] = []
        k = ki
        n = len(self._intervals)
        while k < n:
            bid = self._intervals[k][2]
            run.append(bid)
            blk = net.blocks.get(bid)
            if blk is None or not blk.chain:
                break                       # included the exit (first plain block)
            k += 1
        return run

    def _run_free(self, net: RailNetwork, run) -> bool:
        for b in run:
            blk = net.blocks.get(b)
            if blk is not None and blk.occupant not in (None, self.id):
                return False
        return True

    def _reservation_clamp(self, net: RailNetwork, target: float, ds: float) -> float:
        """How far the head may advance without entering a block it can't hold. Plain next
        block must be free (else stop MERGE_CLEAR short). A CHAIN next block requires the
        whole chain run + safe exit to be free, reserved ATOMICALLY - else the train waits
        before the junction (at the chain signal), holding no junction block, so junctions
        always drain (deadlock-free). With NO chain blocks this reduces to the old guard."""
        cur = self._block_at(self.head_s)
        horizon = min(self.leg_len, self.head_s + max(ds, balance.MERGE_CLEAR))
        for k, (s, e, bid) in enumerate(self._intervals):
            if e <= self.head_s + 1e-6 or bid == cur:
                continue                                  # behind or the current block
            if s > horizon:
                break                                     # nothing within reach to clear
            blk = net.blocks.get(bid)
            if blk is None:
                continue
            if blk.chain:
                if self._run_free(net, self._chain_run(net, k)):
                    return target                         # whole path clear: may enter
                return max(self.head_s, min(target, s - balance.MERGE_CLEAR))
            if blk.occupant in (None, self.id):
                continue                                  # free plain block; keep scanning
            return max(self.head_s, min(target, s - balance.MERGE_CLEAR))
        return target

    def _resolve_chain_claims(self, net: RailNetwork, body: set[int]) -> set[int]:
        """Turn the body/reserve-ahead set into an actually-holdable claim: a chain block is
        only held as part of its WHOLE free run (reserve the entire junction path at once);
        a chain block whose run isn't free is dropped, so we never hold a partial junction."""
        if not any(getattr(net.blocks.get(b), "chain", False) for b in body):
            return body                                   # fast path: no junctions involved
        result = set(body)
        for k, (s, e, bid) in enumerate(self._intervals):
            if bid not in body:
                continue
            blk = net.blocks.get(bid)
            if blk is None or not blk.chain:
                continue
            run = self._chain_run(net, k)
            if self._run_free(net, run):
                result.update(run)
            else:
                result.discard(bid)
        return result

    # ---- movement ---------------------------------------------------------
    def update_movement(self, dt: float, net: RailNetwork, obstacles=None,
                        hard_obstacles=None, ignore_traffic=False) -> None:
        if self.state != "moving":
            return
        if ignore_traffic:                 # anti-deadlock: the most-stuck train ignores SOFT
            obstacles = None               # yielding (priority/region waits) so it stops
                                           # dithering - but it KEEPS the hard guard below, so
                                           # it still never overlaps another car (no collisions)
        if self.fuel_seconds <= 0:
            self.speed = 0.0
            self.stalled = True
            return
        self.stalled = False
        cap = self.max_speed
        if self.hp < self.max_hp * balance.TRAIN_DAMAGED_THRESHOLD:
            cap *= balance.TRAIN_DAMAGED_SPEED         # limp while heavily damaged
        self.speed = min(cap, self.speed + self.accel * dt)
        ds = self.speed * dt
        target = min(self.leg_len, self.head_s + ds)
        region_waiting = False        # legitimately queued for the home-crossing mutex
        traffic_blocked = False       # stopped by another train's car (possible deadlock)

        # block / chain-signal reservation: don't advance into a block we can't hold. A
        # plain occupied block stops us MERGE_CLEAR short; a CHAIN (junction) block requires
        # reserving its whole run + safe exit atomically, else we wait before it. With no
        # chain blocks this is exactly the old single-block merge guard.
        clamped = self._reservation_clamp(net, target, ds)
        if clamped < target:
            target = clamped
            self.speed = 0.0

        # home-cluster interlock: only the mutex holder may move through the central
        # crossing. A train still waiting for the mutex HOLDS ITS POSITION as soon as
        # it gets within approach of the crossing - it does NOT creep up to the edge,
        # so the waiters stay spread around their stations instead of piling onto the
        # boundary and blocking the one train that does have the mutex.
        if not self.holds_junction and not ignore_traffic and self.junc_enter is not None \
                and self.head_s <= self.junc_exit + 1e-6:
            if self._in_region(net) or (self.junc_enter - self.head_s) <= balance.JUNCTION_APPROACH:
                target = self.head_s
                self.speed = 0.0
                self.waiting_for_train = True
                region_waiting = True

        # predictive yield: slow for higher-priority traffic ahead (so the lower
        # train gives way before a crossing rather than nosing into it).
        if obstacles:
            look = min(self.leg_len, target + balance.TRAIN_LOOKAHEAD)
            hx, hy, _ = _point_at(self._pts, self._cum, target)
            bx, by, _ = _point_at(self._pts, self._cum, look)
            cd2 = balance.TRAIN_COLLISION_DIST ** 2
            for ox, oy in obstacles:
                if (hx - ox) ** 2 + (hy - oy) ** 2 < cd2 or (bx - ox) ** 2 + (by - oy) ** 2 < cd2:
                    target = self.head_s
                    self.speed = 0.0
                    self.waiting_for_train = True
                    traffic_blocked = True
                    break

        # hard collision guard: NEVER advance to within collision distance of any
        # other train's car. This is unconditional (applies even to the mutex holder),
        # so two trains can never physically overlap. We check the new head position AND
        # a point a collision-distance further on, so a train brakes BEFORE a graze when
        # another is converging on a crossing/merge (otherwise a fast same-tick approach
        # could close the gap before either yields).
        near = hard_obstacles if hard_obstacles is not None else obstacles
        if near and target > self.head_s:
            cd2 = balance.TRAIN_COLLISION_DIST ** 2
            look = min(self.leg_len, target + balance.TRAIN_COLLISION_DIST)
            hx, hy, _ = _point_at(self._pts, self._cum, target)
            fx, fy, _ = _point_at(self._pts, self._cum, look)
            for ox, oy in near:
                if (hx - ox) ** 2 + (hy - oy) ** 2 < cd2 or (fx - ox) ** 2 + (fy - oy) ** 2 < cd2:
                    target = self.head_s
                    self.speed = 0.0
                    self.waiting_for_train = True
                    traffic_blocked = True
                    break

        moved = target - self.head_s
        if moved > 0:
            self.fuel_seconds -= dt
        # how long this train has been unable to make meaningful progress (used to
        # pick which train to push through if the WHOLE network freezes - see
        # Simulation's global no-progress detector).
        if moved > 0.03:
            self.blocked_time = 0.0
        else:
            self.blocked_time += dt
        _ = (region_waiting, traffic_blocked)   # (flags reserved for future tuning)
        self.head_s = target

        # acquire blocks now under the body; only record ones we actually own,
        # then release any previously-held block no longer under us. Chain (junction)
        # blocks are resolved to whole free runs so we never hold a PARTIAL junction.
        body = self._resolve_chain_claims(net, self._body_blocks())
        owned: set[int] = set()
        for bid in body:
            blk = net.blocks.get(bid)
            if blk is None:
                continue
            if blk.occupant in (None, self.id):
                blk.occupant = self.id
                owned.add(bid)
        for bid in list(self.locked):
            if bid not in owned:
                blk = net.blocks.get(bid)
                if blk is not None and blk.occupant == self.id:
                    blk.occupant = None
        self.locked = owned

        if self.head_s >= self.leg_len - 1e-6:
            self.head_s = self.leg_len
            self.state = "waiting"
            self.wait_timer = 0.0
            self.idle_timer = 0.0
            self.speed = 0.0

    def depart(self, net: RailNetwork) -> None:
        self.begin_leg(net, (self.cur_leg + 1) % len(self.legs))

    # ---- traffic priority / junction interlock ----------------------------
    def traffic_priority(self) -> tuple[int, int, int]:
        """Sort key (lower = higher priority / right of way). Loaded or recalled trains
        clear the network first; then, WITHIN a class, the LONGEST-BLOCKED train wins (in
        whole seconds) so trains contending for a shared junction take turns fairly instead
        of one starving the others; id is the final strict tiebreak (=> a total order, no
        yield cycles). For a disjoint one-train corridor blocked_time stays ~0, so this
        reduces to the old (cls, id) and existing behaviour is unchanged."""
        cls = 0 if (self.recall or self.cargo_total() > 0) else 1
        return (cls, -int(self.blocked_time), self.id)

    def _in_region(self, net: RailNetwork) -> bool:
        """True if any of this train's cars is inside its home throat region."""
        if self.throat_center is None:
            cx, cy, r = net.junction_center[0], net.junction_center[1], net.junction_radius
        else:
            cx, cy, r = self.throat_center[0], self.throat_center[1], self.throat_radius
        r2 = r * r
        for (x, y, _a, _k) in self.car_poses():
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                return True
        return False

    def wants_junction(self, net: RailNetwork) -> bool:
        """A moving train that needs the cluster mutex: it is already inside the
        region, or its path is about to enter it on this leg."""
        if self.junc_enter is None or self.holds_junction or self.state != "moving":
            return False
        if self.head_s > self.junc_exit + 1e-6:        # already past the region
            return False
        return self._in_region(net) or (self.junc_enter - self.head_s) <= balance.JUNCTION_APPROACH

    # ---- rendering --------------------------------------------------------
    def car_poses(self) -> list[tuple[float, float, float, str]]:
        """(x, y, angle_deg, kind) for the loco + each wagon, front to back.

        A car whose offset puts it behind the current leg's start trails onto the
        previous leg's tail, so the train stays one connected unit across station/
        leg boundaries instead of the wagons piling up at the start point."""
        step = balance.ENTITY_LEN + balance.COUPLING
        poses = []
        for i in range(self.wagons + 1):
            d = self.head_s - i * step
            if d >= 0.0:
                x, y, ang = _point_at(self._pts, self._cum, d)
            elif self._prev_pts and self._prev_len + d >= 0.0:
                x, y, ang = _point_at(self._prev_pts, self._prev_cum, self._prev_len + d)
            else:
                x, y, ang = _point_at(self._pts, self._cum, 0.0)
            poses.append((x, y, ang, "loco" if i == 0 else "wagon"))
        return poses

    @property
    def current_station_id(self) -> int:
        return self.legs[self.cur_leg].station_id


def _junction_interval(pts, cum, center, radius):
    """Arc-length span [enter, exit] of a polyline that lies within `radius` of
    `center`, computed analytically per segment (so a long straight that crosses
    the throat between sparse endpoints is still caught). Returns None if it never
    enters. The span is the min-enter/max-exit envelope, so a train holds the
    interlock continuously even if the path grazes out and back in."""
    cx, cy = center
    r2 = radius * radius
    enter = None
    exit_ = None
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        dx, dy = bx - ax, by - ay
        fx, fy = ax - cx, ay - cy
        A = dx * dx + dy * dy
        seglen = cum[i] - cum[i - 1]
        if A < 1e-12:                                   # zero-length segment
            if fx * fx + fy * fy <= r2:
                lo = hi = cum[i - 1]
            else:
                continue
        else:
            B = 2.0 * (fx * dx + fy * dy)
            C = fx * fx + fy * fy - r2
            disc = B * B - 4.0 * A * C
            if disc < 0.0:
                continue                                # never within radius
            sq = math.sqrt(disc)
            t0 = (-B - sq) / (2.0 * A)
            t1 = (-B + sq) / (2.0 * A)
            t0 = max(0.0, min(1.0, t0))
            t1 = max(0.0, min(1.0, t1))
            if t1 - t0 <= 1e-9:
                continue                                # tangent / outside [0,1]
            lo = cum[i - 1] + t0 * seglen
            hi = cum[i - 1] + t1 * seglen
        if enter is None or lo < enter:
            enter = lo
        if exit_ is None or hi > exit_:
            exit_ = hi
    if enter is None:
        return None
    return (enter, exit_)


def _cumulative(pts: list[tuple[float, float]]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[i - 1], pts[i]))
    return cum


def _point_at(pts, cum, dist):
    if not pts:
        return 0.0, 0.0, 0.0
    if len(pts) == 1:
        return pts[0][0], pts[0][1], 0.0
    dist = max(0.0, min(dist, cum[-1]))
    # locate segment
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < dist:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    seg = cum[i] - cum[i - 1]
    t = 0.0 if seg <= 0 else (dist - cum[i - 1]) / seg
    ax, ay = pts[i - 1]
    bx, by = pts[i]
    x = ax + (bx - ax) * t
    y = ay + (by - ay) * t
    ang = math.degrees(math.atan2(by - ay, bx - ax))
    return x, y, ang
