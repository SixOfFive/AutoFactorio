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

    def _build_lane(self, waypoints: list[tuple[int, int]]) -> list[int]:
        """Create directed edges along corners, split so no edge exceeds the
        signal spacing (keeps blocks train-length-bounded). Returns edge ids."""
        edge_ids: list[int] = []
        max_len = float(balance.SIGNAL_SPACING)
        prev_node = self.add_node(*waypoints[0])
        for i in range(1, len(waypoints)):
            x0, y0 = self.nodes[prev_node]
            x1, y1 = waypoints[i]
            seg_len = math.dist((x0, y0), (x1, y1))
            steps = max(1, int(math.ceil(seg_len / max_len)))
            for s in range(1, steps + 1):
                t = s / steps
                nx = _snap(round(x0 + (x1 - x0) * t), balance.RAIL_GRID)
                ny = _snap(round(y0 + (y1 - y0) * t), balance.RAIL_GRID)
                nxt = self.add_node(nx, ny)
                if nxt == prev_node:
                    continue
                edge_ids.append(self._add_edge(prev_node, nxt))
                prev_node = nxt
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
        """Build two one-way lanes between home and a field.

        Returns (out_edges, ret_edges, load_station, unload_station). The train
        loop is: home -> out -> load(field) -> ret -> unload(home) -> repeat.
        """
        g = balance.RAIL_GRID
        # perpendicular offset so the return lane runs parallel to the outbound
        dx, dy = field_pt[0] - home[0], field_pt[1] - home[1]
        d = math.hypot(dx, dy) or 1.0
        off = balance.LANE_OFFSET
        px = _snap(round(-dy / d * off), g)
        py = _snap(round(dx / d * off), g)

        home_a = (_snap(home[0], g), _snap(home[1], g))
        field_a = (_snap(field_pt[0], g), _snap(field_pt[1], g))
        home_b = (home_a[0] + px, home_a[1] + py)
        field_b = (field_a[0] + px, field_a[1] + py)

        out_wp = self._lattice_path(home_a, field_a)
        ret_wp = self._lattice_path(field_b, home_b)
        out_edges = self._build_lane(out_wp)
        ret_edges = self._build_lane(ret_wp)
        self._signalize(out_edges, chain_at_start=True)
        self._signalize(ret_edges, chain_at_start=True)

        load = self._add_station("load", field_a, kind="load")
        unload = self._add_station("unload", home_b, kind="unload", is_home=True)
        return out_edges, ret_edges, load, unload

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
