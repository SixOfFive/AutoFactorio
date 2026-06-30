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

from .. import balance
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
        "ships": {
            "next_id": sim._ship_id, "timer": sim._ship_timer, "launched": sim.ships_launched,
            "list": [{"id": s.id, "reward": s.reward, "jitter": s.jitter,
                      "climb": s.climb, "delivered": s.delivered} for s in sim.ships],
        },
        "explored": _enc_grid(sim.world.explored),
        "patches": [
            {"id": p.id, "reserve": p.reserve, "discovered": p.discovered, "claimed": p.claimed}
            for p in sim.world.patches
        ],
        "kills": sim.kills,
        "robots": {
            "next_id": sim.robots._rid,
            "list": [{"id": r.id, "x": r.x, "y": r.y, "heading": r.heading, "hp": r.hp,
                      "explorer": r.explorer, "carry_coal": r.carry_coal,
                      "carry_fuel": r.carry_fuel,
                      "angle": r.angle, "radius": r.radius, "task": r.task,
                      "target": r.target, "dismantle_phase": r.dismantle_phase,
                      "carry_reclaim": dict(r.carry_reclaim)} for r in sim.robots.values()],
        },
        "animals": {
            "next_aid": sim.animals._aid, "next_hid": sim.animals._hid,
            "spawn_timer": sim.animals._spawn_timer,
            "herd_centers": {str(k): v for k, v in sim.animals.herd_centers.items()},
            "list": [{"id": a.id, "x": a.x, "y": a.y, "herd": a.herd, "hp": a.hp,
                      "state": a.state, "target_robot": a.target_robot}
                     for a in sim.animals.list.values()],
        },
        "economy": {
            "inv": dict(sim.economy.inv),
            "furnaces": sim.economy.furnaces,
            "furnace_tier": sim.economy.furnace_tier,
            "assemblers": sim.economy.assemblers,
            "total_smelted": sim.economy.total_smelted,
            "total_crafted": sim.economy.total_crafted,
            "caps": dict(sim.economy.caps),
        },
        "research": sim.research.to_dict(),
        "net": {
            "counters": {"nid": net._nid, "eid": net._eid, "bid": net._bid, "sid": net._sid},
            "nodes": {str(k): list(v) for k, v in net.nodes.items()},
            "edges": {str(e.id): {"a": e.a, "b": e.b, "points": [list(p) for p in e.points],
                                  "length": e.length, "block_id": e.block_id, "built": e.built}
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
             "buffer_cap": f.buffer_cap, "edge_ids": list(f.edge_ids),
             "station_ids": list(f.station_ids), "rail_used": f.rail_used,
             "state": f.state}
            for f in sim.fields.values()
        ],
        "trains": [
            {"id": t.id, "wagons": t.wagons, "cargo": dict(t.cargo),
             "fuel_seconds": t.fuel_seconds, "speed": t.speed, "state": t.state,
             "cur_leg": t.cur_leg, "head_s": t.head_s, "wait_timer": t.wait_timer,
             "idle_timer": t.idle_timer, "stalled": t.stalled, "hp": t.hp,
             "recall": t.recall,
             "legs": [{"edges": l.edges, "station_id": l.station_id, "wait": list(l.wait)}
                      for l in t.legs]}
            for t in sim.trains.values()
        ],
        "jobs": {
            "next_id": sim._jid,
            "list": [{"id": j.id, "field_id": j.field_id, "x": j.x, "y": j.y,
                      "edge_ids": list(j.edge_ids), "activates_field": j.activates_field,
                      "legs": [{"edges": l.edges, "station_id": l.station_id, "wait": list(l.wait)}
                               for l in j.legs]}
                     for j in sim.jobs.values()],
        },
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

    sim.kills = data.get("kills", 0)

    # orbital ships (forward-compatible: absent in older saves)
    from .simulation import Ship
    sd = data.get("ships", {})
    sim._ship_id = sd.get("next_id", 0)
    sim._ship_timer = sd.get("timer", 0.0)
    sim.ships_launched = sd.get("launched", 0)
    sim.ships = [Ship(s["id"], s["reward"], s.get("jitter", 0.0),
                      s.get("climb", 0.0), s.get("delivered", False))
                 for s in sd.get("list", [])]

    # robots
    from .robots import Robots, Robot
    from .animals import Animals, Animal
    sim.robots = Robots()
    rdata = data.get("robots", {})
    for rd in rdata.get("list", []):
        r = Robot(rd["id"], rd["x"], rd["y"], rd.get("explorer", False))
        r.heading = rd.get("heading", 0.0)
        r.hp = rd.get("hp", 100.0)
        r.carry_coal = rd.get("carry_coal", 0.0)
        r.carry_fuel = rd.get("carry_fuel", 0.0)
        r.angle = rd.get("angle", 0.7)
        r.radius = rd.get("radius", 18.0)
        r.task = rd.get("task", "explore")
        r.target = rd.get("target")
        r.dismantle_phase = rd.get("dismantle_phase")
        r.carry_reclaim = dict(rd.get("carry_reclaim", {}))
        r.tx, r.ty = r._spiral_target()
        sim.robots.list[r.id] = r
    sim.robots._rid = rdata.get("next_id", len(sim.robots.list))
    if not sim.robots.list:                         # always keep an explorer
        sim.robots.add(0.0, 0.0, explorer=True)

    # animals
    sim.animals = Animals(sim.world.seed)
    adata = data.get("animals", {})
    sim.animals._aid = adata.get("next_aid", 0)
    sim.animals._hid = adata.get("next_hid", 0)
    sim.animals._spawn_timer = adata.get("spawn_timer", 0.0)
    sim.animals.herd_centers = {int(k): list(v) for k, v in adata.get("herd_centers", {}).items()}
    for ad in adata.get("list", []):
        sim.animals.list[ad["id"]] = Animal(ad["id"], ad["x"], ad["y"], ad["herd"],
                                            ad.get("hp", 55.0), ad.get("state", "wander"),
                                            ad.get("target_robot"))

    # economy
    e = data["economy"]
    sim.economy.inv.clear()
    for k, v in e["inv"].items():
        sim.economy.inv[k] = v
    # storage caps: start from defaults (forward-compat for old saves) then apply
    sim.economy.caps = dict(balance.STORAGE_CAP_START)
    sim.economy.caps.update({k: int(v) for k, v in e.get("caps", {}).items()})
    # enforce the same invariant as Economy.__init__: inventory never exceeds cap
    for k, c in sim.economy.caps.items():
        if sim.economy.inv.get(k, 0) > c:
            sim.economy.inv[k] = c
    sim.economy.furnaces = e["furnaces"]
    sim.economy.furnace_tier = e["furnace_tier"]
    sim.economy.assemblers = e["assemblers"]
    sim.economy.total_smelted = e["total_smelted"]
    sim.economy.total_crafted = e["total_crafted"]
    if "research" in data:
        sim.research.from_dict(data["research"])
    sim._sync_research()

    # rail network
    net = sim.net
    net.nodes = {int(k): tuple(v) for k, v in data["net"]["nodes"].items()}
    net._pos_to_node = {pos: nid for nid, pos in net.nodes.items()}
    net.out_edges = {nid: [] for nid in net.nodes}
    net.edges = {}
    for k, ed in data["net"]["edges"].items():
        eid = int(k)
        net.edges[eid] = RailEdge(eid, ed["a"], ed["b"],
                                  [tuple(p) for p in ed["points"]], ed["length"], ed["block_id"],
                                  ed.get("built", True))
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
    net.junction_occupant = None         # interlock is transient; re-granted on tick

    # fields
    sim.fields = {}
    for sf in data["fields"]:
        patch = pmap[sf["patch_id"]]
        fld = MiningField(sf["id"], patch, sf["drills"], sf["tier"], sf["load_station_id"],
                          sf["buffer"], sf["buffer_cap"])
        fld.edge_ids = list(sf.get("edge_ids", []))
        fld.station_ids = list(sf.get("station_ids", []))
        fld.rail_used = sf.get("rail_used", 0)
        fld.state = sf.get("state", "active")
        sim.fields[sf["id"]] = fld

    # trains (rebuild geometry, then restore dynamic state)
    sim.trains = {}
    for st in data["trains"]:
        legs = [Leg(l["edges"], l["station_id"], tuple(l["wait"])) for l in st["legs"]]
        t = Train(st["id"], legs, st["wagons"], net, sim.research)
        t.begin_leg(net, st["cur_leg"])
        t.head_s = st["head_s"]
        t.state = st["state"]
        t.speed = st["speed"]
        t.fuel_seconds = st["fuel_seconds"]
        t.cargo = dict(st["cargo"])
        t.wait_timer = st["wait_timer"]
        t.idle_timer = st["idle_timer"]
        t.stalled = st["stalled"]
        t.hp = st.get("hp", t.max_hp)
        t.recall = st.get("recall", False)
        sim.trains[st["id"]] = t

    # construction jobs (robots still building these)
    from .simulation import ConstructionJob
    sim.jobs = {}
    jdata = data.get("jobs", {})
    for jd in jdata.get("list", []):
        legs = [Leg(l["edges"], l["station_id"], tuple(l["wait"])) for l in jd["legs"]]
        sim.jobs[jd["id"]] = ConstructionJob(jd["id"], jd["field_id"], jd["x"], jd["y"],
                                             list(jd["edge_ids"]), legs, jd["activates_field"])
    sim._jid = jdata.get("next_id", len(sim.jobs))

    sim.events = [tuple(ev) for ev in data.get("events", [])]
    sim._depleted_announced = {f.id for f in sim.fields.values() if f.patch.depleted}
