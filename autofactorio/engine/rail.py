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
    built: bool = True                      # False = planned/ghost (robot still building)


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
    aspect: str = "green"                    # 'green' | 'red' (live, for rendering)


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


@dataclass
class Trunk:
    """A shared double-track MAIN LINE serving one angular sector. Its home end is a
    balloon-loop (with the one shared unload station) at TRUNK_HOME_RING; from there
    a straight radial spine runs outward (out_seq) and back (in_seq). Each member
    field attaches a short SIDING at its own radius (nearest spine node), so trains
    share the long spine (one-train-per-block => they follow each other and travel to
    different fields along the same track) while only the short sidings are private.
    The spine is straight, so it can be APPENDED to (extended outward) for a farther
    field without disturbing existing edge ids / legs."""
    id: int
    bearing: float
    home_edges: list[int]                    # balloon loop: unload(A_in) -> A_out
    out_nodes: list[int]                     # spine out node ids, A_out (inner) -> outer
    out_seq: list[int]                       # edge i connects out_nodes[i] -> out_nodes[i+1]
    in_nodes: list[int]                      # spine in node ids, outer -> A_in (inner, last)
    in_seq: list[int]                        # edge i connects in_nodes[i] -> in_nodes[i+1]
    unload_id: int                           # the one shared home unload station
    max_r: float = 0.0                       # current outer radius the spine reaches
    field_ids: list[int] = field(default_factory=list)


class RailNetwork:
    def __init__(self) -> None:
        self.nodes: dict[int, tuple[int, int]] = {}
        self._pos_to_node: dict[tuple[int, int], int] = {}
        self.edges: dict[int, RailEdge] = {}
        self.out_edges: dict[int, list[int]] = {}
        self.blocks: dict[int, Block] = {}
        self.signals: dict[int, Signal] = {}
        self.stations: dict[int, Station] = {}
        self.trunks: dict[int, Trunk] = {}      # shared-track corridors, by sector
        self._nid = 0
        self._eid = 0
        self._bid = 0
        self._sid = 0
        self._tkid = 0
        # legacy single-junction fields (kept for save compat / old code paths)
        self.junction_center: tuple[float, float] = (0.0, 0.0)
        self.junction_radius: float = balance.JUNCTION_RADIUS
        self.junction_occupant: int | None = None
        # per-trunk home-throat interlock: each trunk's turnaround (balloon) is too
        # small for two trains, so it's a mutex - at most one train through it at a
        # time; others queue on the shared spine (see Simulation._arbitrate_junction).
        self.throat_occupant: dict[int, int | None] = {}    # trunk_id -> train id

    def trunk_throat(self, tk: "Trunk") -> tuple[tuple[float, float], float]:
        """Geometry of a trunk's home throat: a circle covering its balloon turnaround
        (where in-lane, out-lane and balloon meet) that only one train may be in."""
        off = balance.LANE_OFFSET
        r0 = balance.TRUNK_HOME_RING
        ux, uy = math.cos(tk.bearing), math.sin(tk.bearing)
        px, py = -uy, ux
        cx = ux * (r0 - off * 0.25) + px * (off * 0.5)
        cy = uy * (r0 - off * 0.25) + py * (off * 0.5)
        return (cx, cy), off * 0.55

    def update_signals(self) -> None:
        """Refresh each signal's red/green aspect for rendering: a signal shows red
        when the block just past it is held by a train, and a chain (throat) signal
        shows red while its trunk's home throat is reserved."""
        occupied_throats = [self.trunk_throat(tk) for tk in self.trunks.values()
                            if self.throat_occupant.get(tk.id) is not None]
        for nid, sig in self.signals.items():
            red = False
            for eid in self.out_edges.get(nid, []):
                e = self.edges.get(eid)
                if e is None:
                    continue
                blk = self.blocks.get(e.block_id)
                if blk is not None and blk.occupant is not None:
                    red = True
                    break
            if sig.kind == "chain" and not red:
                for (cx, cy), rad in occupied_throats:
                    rr = rad + balance.LANE_OFFSET
                    if (sig.pos[0] - cx) ** 2 + (sig.pos[1] - cy) ** 2 <= rr * rr:
                        red = True
                        break
            sig.aspect = "red" if red else "green"

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

    # ---- shared-track trunk network ---------------------------------------
    def find_or_make_trunk(self, bearing: float, reach: float) -> tuple[Trunk, bool]:
        """Return the trunk serving this bearing's sector (building a new one, reaching
        out to `reach` tiles, if none is within TRUNK_MERGE_DEG). 2nd value: created?"""
        best = None
        best_d = math.radians(balance.TRUNK_MERGE_DEG)
        for tk in self.trunks.values():
            if len(tk.field_ids) >= balance.TRUNK_MAX_FIELDS:
                continue                              # full: don't overload its one throat
            d = abs((bearing - tk.bearing + math.pi) % (2 * math.pi) - math.pi)
            if d <= best_d:
                best_d = d
                best = tk
        if best is not None:
            return best, False
        return self.build_trunk(bearing, reach), True

    def _spine_segment(self, a_pt, b_pt) -> tuple[int, int]:
        """One straight signalled spine edge a->b (its own block). Returns (edge, b_node)."""
        an = self.add_node(*a_pt)
        bn = self.add_node(*b_pt)
        eid = self._add_edge_poly(an, bn, [a_pt, b_pt])
        blk = self._new_block()
        blk.edge_ids.append(eid)
        blk.length = self.edges[eid].length
        self.edges[eid].block_id = blk.id
        self.signals.setdefault(an, Signal(an, "rail", (float(a_pt[0]), float(a_pt[1]))))
        return eid, bn

    def build_trunk(self, bearing: float, reach: float) -> Trunk:
        """Lay one sector's shared main line: a home balloon-loop (with the unload
        station) at TRUNK_HOME_RING, then a straight radial spine out to `reach`."""
        g = balance.RAIL_GRID
        off = balance.LANE_OFFSET
        ux, uy = math.cos(bearing), math.sin(bearing)
        px, py = -uy, ux                                  # perpendicular (lane offset dir)
        r0 = balance.TRUNK_HOME_RING
        a_out = (_snap(ux * r0, g), _snap(uy * r0, g))                       # outbound home end
        a_in = (_snap(ux * r0 + px * off, g), _snap(uy * r0 + py * off, g))  # inbound home end
        home_uturn = _arc(a_in, a_out, (-ux, -uy))        # balloon behind home: in-lane -> out-lane
        home_e = self._polyline_to_edges(home_uturn)
        self._signalize(home_e, chain_at_start=True)

        tk = Trunk(self._tkid, bearing, home_e, [self.add_node(*a_out)], [],
                   [], [], -1, float(r0))
        self.trunks[tk.id] = tk
        self._tkid += 1
        # the spine runs from r0 (A_out / A_in) outward to `reach`; the inbound spine's
        # innermost node lands exactly on A_in (the home balloon's open end).
        self._extend_spine(tk, reach)
        # the unload stop sits on the inbound spine ONE block out from the balloon (NOT
        # in the home throat), so a returning train can always pull in to unload without
        # contending for the turnaround interlock - only DEPARTING trains queue for it.
        unload_node = tk.in_nodes[-2] if len(tk.in_nodes) >= 2 else tk.in_nodes[-1]
        unload = self._add_station("unload", self.nodes[unload_node], kind="unload", is_home=True)
        tk.unload_id = unload.id
        return tk

    def _extend_spine(self, tk: Trunk, reach: float) -> None:
        """Append straight spine segments outward (and matching inbound segments) until
        the spine reaches `reach`. Append-only: never disturbs existing edge ids."""
        g = balance.RAIL_GRID
        off = balance.LANE_OFFSET
        ux, uy = math.cos(tk.bearing), math.sin(tk.bearing)
        px, py = -uy, ux
        step = float(balance.SIGNAL_SPACING)
        r = tk.max_r
        new_in_segments = []   # (edge, a_node, b_node) built inner->outer this batch
        while r < reach - 1e-6:
            r2 = min(reach, r + step)
            out_a = (_snap(ux * r, g), _snap(uy * r, g))
            out_b = (_snap(ux * r2, g), _snap(uy * r2, g))
            eid, bnode = self._spine_segment(out_a, out_b)
            tk.out_seq.append(eid)
            tk.out_nodes.append(bnode)
            # inbound runs the OTHER way (r2 -> r) on the offset lane
            in_a = (_snap(ux * r2 + px * off, g), _snap(uy * r2 + py * off, g))
            in_b = (_snap(ux * r + px * off, g), _snap(uy * r + py * off, g))
            ie, ib = self._spine_segment(in_a, in_b)
            new_in_segments.append((ie, self.add_node(*in_a), ib))
            r = r2
        # inbound spine is ordered OUTER -> inner (A_in last). This batch was built
        # inner->outer, so reverse it, and prepend ahead of any existing (more inner)
        # inbound spine so the full sequence stays outer->inner and contiguous.
        if new_in_segments:
            rev = list(reversed(new_in_segments))           # outer-most first
            seq = [e for (e, _a, _b) in rev]
            nodes = [rev[0][1]] + [b for (_e, _a, b) in rev]  # outer node, then each inner b
            if tk.in_nodes and nodes[-1] == tk.in_nodes[0]:   # join coincides -> drop dup
                nodes = nodes[:-1]
            tk.in_seq[:0] = seq
            tk.in_nodes[:0] = nodes
        tk.max_r = max(tk.max_r, reach)

    def attach_field(self, bearing: float, field_pt: tuple[int, int]):
        """Attach a field to its sector's main line via a short SIDING at the field's
        own radius. Returns (legA_edges, legB_edges, branch_edges, new_edges, load,
        unload, trunk, created): legA/legB are the full loop (shared spine slice +
        this field's siding); branch_edges are the field-owned siding to reclaim;
        new_edges are the not-yet-built edges a robot must lay."""
        g = balance.RAIL_GRID
        off = balance.LANE_OFFSET
        rP = math.hypot(field_pt[0], field_pt[1])
        before = set(self.edges.keys())                    # snapshot before any new track
        tk, created = self.find_or_make_trunk(bearing, rP + balance.TRUNK_STEM_LEN)
        if rP + 2.0 > tk.max_r:                            # ensure the spine reaches the field
            self._extend_spine(tk, rP + balance.TRUNK_STEM_LEN)
        spine_new = [e for e in self.edges.keys() if e not in before]  # new spine (if created/extended)

        # nearest spine nodes (out + in) to the field's radius. The inbound attach is
        # clamped to be no closer than the unload node (idx_unload), so a returning train
        # always routes DOWN the spine to the unload stop (never inside the throat).
        idx_unload = max(0, len(tk.in_nodes) - 2)
        k_out = self._nearest_spine(tk.out_nodes, field_pt)
        k_in = min(self._nearest_spine(tk.in_nodes, field_pt), idx_unload)
        out_node = tk.out_nodes[k_out]
        in_node = tk.in_nodes[k_in]
        out_pos = self.nodes[out_node]
        in_pos = self.nodes[in_node]

        ux, uy = math.cos(tk.bearing), math.sin(tk.bearing)
        px, py = -uy, ux
        fa = (float(field_pt[0]), float(field_pt[1]))                       # load point
        fb = (field_pt[0] + px * off, field_pt[1] + py * off)               # U-turn end
        # The siding peels off / rejoins the spine TANGENT to it (along +/-u), and the
        # field turnaround is a half-loop tangent to +/-u too, so every join is smooth:
        #   out spine (heading +u) -> sid_out -> fa -> field balloon -> fb -> sid_in ->
        #   in spine (heading -u). No sharp corners anywhere.
        sid_out_poly = _hermite(out_pos, (ux, uy), fa, (ux, uy))           # spine -> fa (load)
        field_uturn = _arc(fa, fb, (ux, uy))                               # fa -> fb, tangent +/-u
        sid_in_poly = _hermite(fb, (-ux, -uy), in_pos, (-ux, -uy))         # fb -> in spine
        sid_out = self._polyline_to_edges(sid_out_poly)
        sid_in = self._polyline_to_edges(field_uturn[:-1] + sid_in_poly)   # fa -> fb -> spine
        self._signalize(sid_out)
        self._signalize(sid_in)
        load = self._add_station("load", fa, kind="load")
        unload = self.stations[tk.unload_id]

        # leg A (unload stop -> field load): finish the inbound spine into the balloon
        # (unload_node .. A_in), loop the balloon (A_in -> A_out), run the outbound spine
        # (A_out .. out_node), then the siding out to the load stop.
        legA = (list(tk.in_seq[idx_unload:]) + list(tk.home_edges)
                + list(tk.out_seq[:k_out]) + list(sid_out))
        # leg B (field load -> unload stop): siding in, then down the inbound spine from
        # the field's attach node to the unload stop (which is one block short of the
        # balloon, OUTSIDE the throat).
        legB = list(sid_in) + list(tk.in_seq[k_in:idx_unload])
        branch_edges = list(sid_out) + list(sid_in)
        # robot must lay: any new spine (incl. the balloon when the trunk was created)
        # plus this field's siding. spine_new already contains home_edges when created.
        new_edges = list(spine_new) + branch_edges
        return legA, legB, branch_edges, new_edges, load, unload, tk, created

    def _nearest_spine(self, node_ids: list[int], pt) -> int:
        """Index of the spine node at the closest RADIUS to pt. Matching by radius (not
        raw distance) makes each field attach at the spine point abreast of it, so fields
        at different distances spread out along the spine instead of bunching at the
        inner nodes (which caused their sidings to converge at the home throat)."""
        pr = math.hypot(pt[0], pt[1])
        best_i, best_d = 0, math.inf
        for i, nid in enumerate(node_ids):
            nx, ny = self.nodes[nid]
            d = abs(math.hypot(nx, ny) - pr)
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    def detach_field(self, trunk_id: int, field_id: int, branch_edges, load_station_id) -> None:
        """Reclaim a field: remove its siding + load station. If its trunk now has no
        fields left, tear down the shared spine + balloon + unload station too."""
        self.remove_edges(branch_edges)
        self.remove_station(load_station_id)
        tk = self.trunks.get(trunk_id)
        if tk is None:
            return
        if field_id in tk.field_ids:
            tk.field_ids.remove(field_id)
        if not tk.field_ids:
            self.remove_edges(list(tk.home_edges) + list(tk.out_seq) + list(tk.in_seq))
            self.remove_station(tk.unload_id)
            self.trunks.pop(trunk_id, None)

    def _add_station(self, base_name: str, pos: tuple[int, int], kind: str,
                     is_home: bool = False) -> Station:
        nid = self.add_node(*pos)
        sid = self._sid
        self._sid += 1
        name = f"{base_name}-{sid}"
        st = Station(sid, name, nid, self.node_pos(nid), kind, is_home=is_home)
        self.stations[sid] = st
        return st

    # ---- removal (reclaiming a depleted field's track) --------------------
    def remove_edges(self, edge_ids) -> None:
        for eid in edge_ids:
            e = self.edges.pop(eid, None)
            if e is None:
                continue
            lst = self.out_edges.get(e.a)
            if lst and eid in lst:
                lst.remove(eid)
            self.blocks.pop(e.block_id, None)
            self.signals.pop(e.a, None)

    def remove_station(self, sid: int) -> None:
        self.stations.pop(sid, None)

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


def _hermite(p0, t0, p1, t1, samples: int = 18):
    """Smooth cubic curve from p0 to p1 leaving along unit tangent t0 and arriving
    along unit tangent t1 (a Bezier with the tangents as control handles). Used for
    turnouts/sidings so they peel off and rejoin the straight spine TANGENTIALLY -
    no sharp corner where a siding meets the main line."""
    k = max(2.0, math.dist(p0, p1) * 0.5)
    c0 = (p0[0] + t0[0] * k, p0[1] + t0[1] * k)
    c1 = (p1[0] - t1[0] * k, p1[1] - t1[1] * k)
    pts = []
    for i in range(samples + 1):
        t = i / samples
        mt = 1.0 - t
        a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        pts.append((a * p0[0] + b * c0[0] + c * c1[0] + d * p1[0],
                    a * p0[1] + b * c0[1] + c * c1[1] + d * p1[1]))
    return pts


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
