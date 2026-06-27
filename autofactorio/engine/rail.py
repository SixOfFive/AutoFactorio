"""Directed rail network: nodes, one-way edges, blocks, signals, stations.

Design (from the research brief):
  * Rail nodes live only on the 2-tile lattice (even tile coords).
  * Every edge is DIRECTED (a -> b). A train may only traverse it that way, so
    head-on collisions are structurally impossible.
  * Track is built as TWO PARALLEL one-way lanes (out + back), never a shared
    two-way line.
  * Collision avoidance = one-train-per-block mutex. Here each edge is its own
    block with an `occupant` lock; trains acquire/release blocks as they move
    (see trains.py). Signals are placed at block boundaries for fidelity/visuals
    and as the hooks for future shared-track routing.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from .. import balance


@dataclass
class RailEdge:
    id: int
    a: int                                  # from-node id
    b: int                                  # to-node id
    points: list[tuple[float, float]]       # world polyline a..b (tiles)
    length: float
    block_id: int = -1


@dataclass
class Block:
    id: int
    edge_ids: list[int] = field(default_factory=list)
    length: float = 0.0
    occupant: int | None = None             # train id holding the mutex


@dataclass
class Signal:
    node_id: int
    kind: str                                # 'rail' | 'chain'
    pos: tuple[float, float] = (0.0, 0.0)


@dataclass
class Station:
    id: int
    name: str
    node_id: int
    pos: tuple[float, float]
    kind: str                                # 'load' | 'unload'
    field_id: int | None = None              # source field for a load stop
    is_home: bool = False
    enabled: bool = True
    coal_buffer: int = 0                     # coal available here to refuel trains
    reserved_by: int | None = None


class RailNetwork:
    def __init__(self) -> None:
        self.nodes: dict[int, tuple[int, int]] = {}
        self._pos_to_node: dict[tuple[int, int], int] = {}
        self.edges: dict[int, RailEdge] = {}
        self.out_edges: dict[int, list[int]] = {}
        self.blocks: dict[int, Block] = {}
        self.signals: dict[int, Signal] = {}
        self.stations: dict[int, Station] = {}
        self._nid = 0
        self._eid = 0
        self._bid = 0
        self._sid = 0

    # ---- primitives -------------------------------------------------------
    def add_node(self, tx: int, ty: int) -> int:
        key = (tx, ty)
        if key in self._pos_to_node:
            return self._pos_to_node[key]
        nid = self._nid
        self._nid += 1
        self.nodes[nid] = key
        self._pos_to_node[key] = nid
        self.out_edges[nid] = []
        return nid

    def node_pos(self, nid: int) -> tuple[float, float]:
        return self.nodes[nid]

    def _add_edge(self, a: int, b: int) -> int:
        pa = self.nodes[a]
        pb = self.nodes[b]
        length = math.dist(pa, pb)
        eid = self._eid
        self._eid += 1
        self.edges[eid] = RailEdge(eid, a, b, [tuple(map(float, pa)), tuple(map(float, pb))], length)
        self.out_edges[a].append(eid)
        return eid

    def _new_block(self) -> Block:
        b = Block(self._bid)
        self.blocks[b.id] = b
        self._bid += 1
        return b

    # ---- lane construction ------------------------------------------------
    def _lattice_path(self, start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
        """Corners of a diagonal-then-straight route on the 2-tile lattice."""
        g = balance.RAIL_GRID
        sx, sy = _snap(start[0], g), _snap(start[1], g)
        ex, ey = _snap(end[0], g), _snap(end[1], g)
        pts = [(sx, sy)]
        x, y = sx, sy
        guard = 0
        while (x, y) != (ex, ey) and guard < 10000:
            guard += 1
            dx = _sign(ex - x) * g
            dy = _sign(ey - y) * g
            if x != ex and y != ey:
                x += dx; y += dy           # diagonal
            elif x != ex:
                x += dx                    # straight horizontal
            else:
                y += dy                    # straight vertical
            pts.append((x, y))
        # compress collinear runs into corners
        return _corners(pts)

    def _add_edge_poly(self, a: int, b: int, points: list[tuple[float, float]]) -> int:
        pts = [tuple(map(float, p)) for p in points]
        length = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
        eid = self._eid
        self._eid += 1
        self.edges[eid] = RailEdge(eid, a, b, pts, length)
        self.out_edges[a].append(eid)
        return eid

    def _polyline_to_edges(self, poly: list[tuple[float, float]]) -> list[int]:
        """Chop a dense (possibly curved) polyline into directed edges of about
        SIGNAL_SPACING arc-length, one block per edge. Returns edge ids."""
        edge_ids: list[int] = []
        start = self.add_node(*poly[0])
        chunk = [poly[0]]
        acc = 0.0
        for i in range(1, len(poly)):
            acc += math.dist(poly[i - 1], poly[i])
            chunk.append(poly[i])
            if acc >= balance.SIGNAL_SPACING and i < len(poly) - 1:
                end = self.add_node(*poly[i])
                edge_ids.append(self._add_edge_poly(start, end, chunk))
                start, chunk, acc = end, [poly[i]], 0.0
        if len(chunk) >= 2:
            end = self.add_node(*poly[-1])
            edge_ids.append(self._add_edge_poly(start, end, chunk))
        return edge_ids

    def _signalize(self, edge_ids: list[int], chain_at_start: bool = False) -> None:
        """One block per edge; drop a signal at each block boundary node."""
        for i, eid in enumerate(edge_ids):
            e = self.edges[eid]
            blk = self._new_block()
            blk.edge_ids.append(eid)
            blk.length = e.length
            e.block_id = blk.id
            kind = "chain" if (i == 0 and chain_at_start) else "rail"
            self.signals.setdefault(e.a, Signal(e.a, kind, self.node_pos(e.a)))

    def build_link(self, home: tuple[int, int], field_pt: tuple[int, int]):
        """Build one continuous, smooth, collision-free loop to a field.

        The loop has two one-way lanes joined by wide U-turns at each end, with all
        corners rounded so trains never turn sharp or snap direction. Two legs:
          A: home -> (home U-turn) -> out lane -> field   (ends at the LOAD stop)
          B: field -> (field U-turn) -> return lane -> home (ends at the UNLOAD stop)
        Because leg B starts exactly where leg A ends (and vice-versa), motion is
        continuous - no teleport between legs.

        Returns (legA_edges, legB_edges, load_station, unload_station).
        """
        g = balance.RAIL_GRID
        dx, dy = field_pt[0] - home[0], field_pt[1] - home[1]
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d                     # unit home->field
        px, py = -uy, ux                            # perpendicular unit
        off = balance.LANE_OFFSET

        home_a = (_snap(home[0], g), _snap(home[1], g))
        field_a = (_snap(field_pt[0], g), _snap(field_pt[1], g))
        home_b = (_snap(home_a[0] + px * off, g), _snap(home_a[1] + py * off, g))
        field_b = (_snap(field_a[0] + px * off, g), _snap(field_a[1] + py * off, g))

        out_poly = _round_corners(self._lattice_path(home_a, field_a), balance.CURVE_RADIUS)
        ret_poly = _round_corners(self._lattice_path(field_b, home_b), balance.CURVE_RADIUS)
        field_uturn = _arc(field_a, field_b, (ux, uy))      # bulge beyond the field
        home_uturn = _arc(home_b, home_a, (-ux, -uy))       # bulge behind home

        legA_poly = home_uturn[:-1] + out_poly              # home_b -> home_a -> field_a
        legB_poly = field_uturn[:-1] + ret_poly             # field_a -> field_b -> home_b
        legA = self._polyline_to_edges(legA_poly)
        legB = self._polyline_to_edges(legB_poly)
        self._signalize(legA, chain_at_start=True)
        self._signalize(legB, chain_at_start=True)

        load = self._add_station("load", field_a, kind="load")
        unload = self._add_station("unload", home_b, kind="unload", is_home=True)
        return legA, legB, load, unload

    def _add_station(self, base_name: str, pos: tuple[int, int], kind: str,
                     is_home: bool = False) -> Station:
        nid = self.add_node(*pos)
        sid = self._sid
        self._sid += 1
        name = f"{base_name}-{sid}"
        st = Station(sid, name, nid, self.node_pos(nid), kind, is_home=is_home)
        self.stations[sid] = st
        return st

    # ---- routing (Dijkstra over directed edges; used for flexible links) --
    def route(self, a: int, b: int) -> list[int] | None:
        """Cheapest directed edge path a->b, penalizing occupied blocks."""
        if a == b:
            return []
        dist = {a: 0.0}
        prev: dict[int, tuple[int, int]] = {}
        pq = [(0.0, a)]
        while pq:
            cost, n = heapq.heappop(pq)
            if n == b:
                break
            if cost > dist.get(n, math.inf):
                continue
            for eid in self.out_edges.get(n, []):
                e = self.edges[eid]
                blk = self.blocks.get(e.block_id)
                pen = balance.OCCUPANCY_PENALTY if (blk and blk.occupant is not None) else 0.0
                nc = cost + e.length + pen
                if nc < dist.get(e.b, math.inf):
                    dist[e.b] = nc
                    prev[e.b] = (n, eid)
                    heapq.heappush(pq, (nc, e.b))
        if b not in prev and b != a:
            return None
        path: list[int] = []
        cur = b
        while cur != a:
            pn, eid = prev[cur]
            path.append(eid)
            cur = pn
        path.reverse()
        return path

    # ---- helpers ----------------------------------------------------------
    def edge_route_length(self, edge_ids: list[int]) -> float:
        return sum(self.edges[e].length for e in edge_ids)

    def total_rail_length(self) -> float:
        return sum(e.length for e in self.edges.values())


def _round_corners(pts, radius: float, step: float = 2.0):
    """Fillet each interior corner with a quadratic Bezier (tangent to both
    segments) so the polyline has no sharp angles. Trim distance is clamped to
    half of each adjacent segment so consecutive fillets never overlap."""
    pts = [tuple(map(float, p)) for p in pts]
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        l1 = math.hypot(ax - bx, ay - by)
        l2 = math.hypot(cx - bx, cy - by)
        if l1 < 1e-6 or l2 < 1e-6:
            out.append((bx, by))
            continue
        dd = min(radius, l1 * 0.5, l2 * 0.5)
        p1 = (bx + (ax - bx) / l1 * dd, by + (ay - by) / l1 * dd)
        p2 = (bx + (cx - bx) / l2 * dd, by + (cy - by) / l2 * dd)
        out.append(p1)
        n = max(2, int(dd * 2 / step))
        for k in range(1, n):
            t = k / n
            mt = 1 - t
            out.append((mt * mt * p1[0] + 2 * mt * t * bx + t * t * p2[0],
                        mt * mt * p1[1] + 2 * mt * t * by + t * t * p2[1]))
        out.append(p2)
    out.append(pts[-1])
    return out


def _arc(p_from, p_to, bulge_unit, samples: int = 16):
    """A 180-degree arc from p_from to p_to bulging toward `bulge_unit`. With the
    two points offset perpendicular to the lane, the arc's tangents line up with
    the lanes, giving a smooth turning loop."""
    cx, cy = (p_from[0] + p_to[0]) * 0.5, (p_from[1] + p_to[1]) * 0.5
    vfx, vfy = p_from[0] - cx, p_from[1] - cy        # radius vector at p_from
    r = math.hypot(vfx, vfy)
    bx, by = bulge_unit
    pts = []
    for k in range(samples + 1):
        a = math.pi * k / samples
        ca, sa = math.cos(a), math.sin(a)
        pts.append((cx + vfx * ca + bx * r * sa, cy + vfy * ca + by * r * sa))
    return pts


def _snap(v: float, g: int) -> int:
    return int(round(v / g)) * g


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def _corners(pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        # keep the point only if direction changes
        if (bx - ax, by - ay) != (cx - bx, cy - by):
            out.append(pts[i])
    out.append(pts[-1])
    return out
