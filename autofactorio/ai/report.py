"""Compact game-state report handed to the director each decision turn.

Kept small and flat so a 4B model can reason over it quickly. Distances are from
home (0,0); only the nearest unclaimed patches are listed.
"""

from __future__ import annotations

import math

from .. import balance

_INV_KEYS = [
    "iron_plate", "copper_plate", "steel_plate", "stone", "coal",
    "rail", "rail_signal", "train_stop", "electric_drill", "burner_drill",
    "stone_furnace", "assembler", "locomotive", "cargo_wagon",
]


def build_report(sim) -> dict:
    eco = sim.economy
    inv = {k: int(eco.inv.get(k, 0)) for k in _INV_KEYS if eco.inv.get(k, 0)}

    fields = []
    for f in sim.fields.values():
        fields.append({
            "id": f.id,
            "ore": f.patch.ore,
            "drills": f.drills,
            "reserve": int(f.patch.reserve),
            "buffer": int(f.buffer),
            "buffer_full": f.buffer >= f.buffer_cap * 0.9,
            "depleted": f.patch.depleted,
        })

    patches = []
    for p in sorted(sim.world.claimable_patches(),
                    key=lambda p: math.hypot(p.cx, p.cy))[:8]:
        patches.append({
            "id": p.id,
            "ore": p.ore,
            "dist": int(math.hypot(p.cx, p.cy)),
            "reserve": int(p.reserve),
            "affordable": sim.can_build_field(p),
        })

    # per-resource storage: list anything getting full so the director can expand
    # it (storage is per-resource and finite; full storage stalls the economy).
    storage = {}
    backing_up = []
    for k in eco.caps:
        frac = eco.fill_fraction(k)
        if frac >= 0.6:
            storage[k] = f"{int(eco.inv.get(k, 0))}/{eco.cap_of(k)}"
        if frac >= balance.STORAGE_RELIEF_FRACTION:
            backing_up.append(k)

    s = sim.stats()
    flags = []
    if any(eco.fill_fraction(o) >= 0.7 for o in ("iron_ore", "copper_ore", "coal", "stone")):
        flags.append("ORE_BACKING_UP")          # smelting can't keep up -> build_furnace
    if any(eco.fill_fraction(o) >= 0.7 for o in ("iron_plate", "copper_plate", "steel_plate")):
        flags.append("PLATES_BACKING_UP")       # crafting can't keep up -> build_assembler
    if backing_up:
        flags.append("STORAGE_FULL")           # see storage_full[] for which items
    if any(f.patch.depleted for f in sim.fields.values()):
        flags.append("DEPLETED_FIELDS")
    if s["damaged_trains"]:
        flags.append("DAMAGED_TRAINS")
    if s["animals"] > 8 and s["robots"] < sim.research.max_robots and sim.can_build_robot():
        flags.append("WILDLIFE_PRESSURE")
    if eco.inv.get("coal", 0) < 150:
        flags.append("LOW_COAL")
    if s["stalled_trains"]:
        flags.append("TRAINS_STALLED_NO_FUEL")
    if not patches:
        flags.append("NO_CLAIMABLE_PATCHES")
    ore_fields = {f.patch.ore for f in sim.fields.values()}
    if "coal" not in ore_fields:
        flags.append("NO_COAL_FIELD")
    if "iron_ore" not in ore_fields:
        flags.append("NO_IRON_FIELD")

    nxt = sim.research.next_tech()
    research = {"level": sim.research.level}
    if nxt is not None:
        research["next"] = {"name": nxt["name"], "desc": nxt["desc"],
                            "affordable": eco.have(nxt["cost"])}

    return {
        "time_s": int(sim.time),
        "inventory": inv,
        "storage": storage,
        "storage_full": backing_up,            # resource names whose storage is full
        "research": research,
        "production": {
            "furnaces": eco.furnaces,
            "assemblers": eco.assemblers,
            "smelted_total": eco.total_smelted,
            "crafted_total": eco.total_crafted,
            "ore_delivered_total": sim.delivered_total,
        },
        "fields": fields,
        "available_patches": patches,
        "trains": {"count": len(sim.trains),
                   "stalled": s["stalled_trains"],
                   "damaged": s["damaged_trains"]},
        "robots": {"count": s["robots"], "max": s["max_robots"],
                   "can_build": sim.can_build_robot()},
        "animals": s["animals"],
        "flags": flags,
    }
