"""Save / load the full simulation state to JSON.

We serialize the authoritative mutable state and rebuild derived structures on
load. Ore patches are regenerated from the seed (so positions match) and then the
mutable per-patch fields (reserve/discovered/claimed) are overlaid by id. The rail
graph, fields, trains, economy, scout, and fog grid are stored directly. Block
locks are cleared on load and re-acquired by trains on the next tick.
"""

from __future__ import annotations

import base64
import json
import os
import zlib

import numpy as np

from .rail import RailEdge, Block, Signal, Station
from .mining import MiningField
from .trains import Train, Leg

SAVE_VERSION = 1


# ---- fog grid (de)compression --------------------------------------------
def _enc_grid(a: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(a.tobytes())).decode("ascii")


def _dec_grid(s: str, shape) -> np.ndarray:
    raw = zlib.decompress(base64.b64decode(s.encode("ascii")))
    return np.frombuffer(raw, dtype=np.uint8).reshape(shape).copy()


# ---- save -----------------------------------------------------------------
def save_game(sim, path: str) -> None:
    net = sim.net
    data = {
        "version": SAVE_VERSION,
        "seed": sim.world.seed,
        "time": sim.time,
        "speed": sim.speed,
        "delivered_total": sim.delivered_total,
        "counters": {"fid": sim._fid, "tid": sim._tid},
        "explored": _enc_grid(sim.world.explored),
        "patches": [
            {"id": p.id, "reserve": p.reserve, "discovered": p.discovered, "claimed": p.claimed}
            for p in sim.world.patches
        ],
        "scout": {"x": sim.scout.x, "y": sim.scout.y, "angle": sim.scout.angle,
                  "radius": sim.scout.radius, "heading": sim.scout.heading},
        "economy": {
            "inv": dict(sim.economy.inv),
            "furnaces": sim.economy.furnaces,
            "furnace_tier": sim.economy.furnace_tier,
            "assemblers": sim.economy.assemblers,
            "total_smelted": sim.economy.total_smelted,
            "total_crafted": sim.economy.total_crafted,
        },
        "net": {
            "counters": {"nid": net._nid, "eid": net._eid, "bid": net._bid, "sid": net._sid},
            "nodes": {str(k): list(v) for k, v in net.nodes.items()},
            "edges": {str(e.id): {"a": e.a, "b": e.b, "points": [list(p) for p in e.points],
                                  "length": e.length, "block_id": e.block_id}
                      for e in net.edges.values()},
            "blocks": {str(b.id): {"edge_ids": b.edge_ids, "length": b.length}
                       for b in net.blocks.values()},
            "signals": {str(nid): {"kind": s.kind, "pos": list(s.pos)}
                        for nid, s in net.signals.items()},
            "stations": {str(s.id): {"name": s.name, "node_id": s.node_id, "pos": list(s.pos),
                                     "kind": s.kind, "field_id": s.field_id, "is_home": s.is_home,
                                     "enabled": s.enabled, "coal_buffer": s.coal_buffer}
                         for s in net.stations.values()},
        },
        "fields": [
            {"id": f.id, "patch_id": f.patch.id, "drills": f.drills, "tier": f.tier,
             "load_station_id": f.load_station_id, "buffer": f.buffer,
             "buffer_cap": f.buffer_cap}
            for f in sim.fields.values()
        ],
        "trains": [
            {"id": t.id, "wagons": t.wagons, "cargo": dict(t.cargo),
             "fuel_seconds": t.fuel_seconds, "speed": t.speed, "state": t.state,
             "cur_leg": t.cur_leg, "head_s": t.head_s, "wait_timer": t.wait_timer,
             "idle_timer": t.idle_timer, "stalled": t.stalled,
             "legs": [{"edges": l.edges, "station_id": l.station_id, "wait": list(l.wait)}
                      for l in t.legs]}
            for t in sim.trains.values()
        ],
        "events": sim.events[-60:],
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


# ---- load -----------------------------------------------------------------
def load_into(sim, path: str) -> None:
    """Load a save file into an existing Simulation built with the SAME seed."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("version") != SAVE_VERSION:
        raise ValueError(f"unsupported save version {data.get('version')}")

    sim.time = data["time"]
    sim.speed = data["speed"]
    sim.delivered_total = data["delivered_total"]
    sim._fid = data["counters"]["fid"]
    sim._tid = data["counters"]["tid"]

    # world (rebuild from the saved seed if it differs, so patches line up)
    if data["seed"] != sim.world.seed:
        from .world import World
        sim.world = World(data["seed"])
    sim.world.explored = _dec_grid(data["explored"], sim.world.explored.shape)
    pmap = {p.id: p for p in sim.world.patches}
    for sp in data["patches"]:
        p = pmap.get(sp["id"])
        if p is not None:
            p.reserve = sp["reserve"]
            p.discovered = sp["discovered"]
            p.claimed = sp["claimed"]

    sc = data["scout"]
    sim.scout.x, sim.scout.y = sc["x"], sc["y"]
    sim.scout.angle, sim.scout.radius = sc["angle"], sc["radius"]
    sim.scout.heading = sc["heading"]
    sim.scout.tx, sim.scout.ty = sim.scout._target()

    # economy
    e = data["economy"]
    sim.economy.inv.clear()
    for k, v in e["inv"].items():
        sim.economy.inv[k] = v
    sim.economy.furnaces = e["furnaces"]
    sim.economy.furnace_tier = e["furnace_tier"]
    sim.economy.assemblers = e["assemblers"]
    sim.economy.total_smelted = e["total_smelted"]
    sim.economy.total_crafted = e["total_crafted"]

    # rail network
    net = sim.net
    net.nodes = {int(k): tuple(v) for k, v in data["net"]["nodes"].items()}
    net._pos_to_node = {pos: nid for nid, pos in net.nodes.items()}
    net.out_edges = {nid: [] for nid in net.nodes}
    net.edges = {}
    for k, ed in data["net"]["edges"].items():
        eid = int(k)
        net.edges[eid] = RailEdge(eid, ed["a"], ed["b"],
                                  [tuple(p) for p in ed["points"]], ed["length"], ed["block_id"])
        net.out_edges.setdefault(ed["a"], []).append(eid)
    net.blocks = {int(k): Block(int(k), b["edge_ids"], b["length"], None)
                  for k, b in data["net"]["blocks"].items()}
    net.signals = {int(k): Signal(int(k), s["kind"], tuple(s["pos"]))
                   for k, s in data["net"]["signals"].items()}
    net.stations = {}
    for k, s in data["net"]["stations"].items():
        sid = int(k)
        net.stations[sid] = Station(sid, s["name"], s["node_id"], tuple(s["pos"]), s["kind"],
                                    s["field_id"], s["is_home"], s["enabled"], s["coal_buffer"], None)
    c = data["net"]["counters"]
    net._nid, net._eid, net._bid, net._sid = c["nid"], c["eid"], c["bid"], c["sid"]

    # fields
    sim.fields = {}
    for sf in data["fields"]:
        patch = pmap[sf["patch_id"]]
        fld = MiningField(sf["id"], patch, sf["drills"], sf["tier"], sf["load_station_id"],
                          sf["buffer"], sf["buffer_cap"])
        sim.fields[sf["id"]] = fld

    # trains (rebuild geometry, then restore dynamic state)
    sim.trains = {}
    for st in data["trains"]:
        legs = [Leg(l["edges"], l["station_id"], tuple(l["wait"])) for l in st["legs"]]
        t = Train(st["id"], legs, st["wagons"], net)
        t.begin_leg(net, st["cur_leg"])
        t.head_s = st["head_s"]
        t.state = st["state"]
        t.speed = st["speed"]
        t.fuel_seconds = st["fuel_seconds"]
        t.cargo = dict(st["cargo"])
        t.wait_timer = st["wait_timer"]
        t.idle_timer = st["idle_timer"]
        t.stalled = st["stalled"]
        sim.trains[st["id"]] = t

    sim.events = [tuple(ev) for ev in data.get("events", [])]
    sim._depleted_announced = {f.id for f in sim.fields.values() if f.patch.depleted}
