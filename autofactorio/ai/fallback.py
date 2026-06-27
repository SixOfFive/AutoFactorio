"""Heuristic director used when the LLM gateway is disabled or unreachable.

Emits the same {"reasoning", "actions"} shape as the LLM so the apply path is
identical. Strategy: secure coal + iron first, then expand to the nearest
affordable patch (favoring ore types we have fewest of), relieve backed-up
fields with extra trains, and otherwise scale home production.
"""

from __future__ import annotations

import math
from collections import Counter

from .. import balance


def _dist(p) -> float:
    return math.hypot(p.cx, p.cy)


def decide(sim, report) -> dict:
    eco = sim.economy
    patches = sorted(sim.world.claimable_patches(), key=_dist)
    ore_fields = Counter(f.patch.ore for f in sim.fields.values())
    coal = eco.inv.get("coal", 0)

    def field_action(p, why):
        return {"reasoning": why, "actions": [{"action": "build_field", "patch_id": p.id}]}

    # 0. decommission newly-exhausted fields (recall trains, then robots tear up track)
    for f in list(sim.fields.values()):
        if f.patch.depleted and getattr(f, "state", "active") == "active":
            return {"reasoning": f"Field #{f.id} patch is exhausted; decommissioning it.",
                    "actions": [{"action": "abandon_field", "field_id": f.id}]}

    # 1. secure one field of every essential ore type ASAP - all four are needed
    #    for the tech tree (iron+copper -> circuits/locos, coal -> fuel, stone ->
    #    rails). Missing any one stalls expansion, so claim them first.
    for ore in ("iron_ore", "copper_ore", "coal", "stone"):
        if ore_fields.get(ore, 0) == 0:
            p = next((p for p in patches if p.ore == ore and sim.can_build_field(p)), None)
            if p:
                return field_action(p, f"Securing first {ore.replace('_', ' ')} field "
                                       f"(patch #{p.id}).")

    # 1b. deploy a robot when there's a construction backlog, wildlife pressure,
    #     a damaged train, or we just want more than one unit
    stats = sim.stats()
    if sim.can_build_robot() and (len(sim.jobs) > len(sim.robots) or stats["animals"] > 6
                                  or stats["damaged_trains"] > 0 or len(sim.robots) < 2):
        return {"reasoning": "Deploying a robot (build/repair/defense/exploration).",
                "actions": [{"action": "build_robot"}]}

    # 2. advance tech whenever the next level is affordable (science accumulates
    #    from surplus, so this fires periodically and compounds the whole economy)
    nxt = sim.research.next_tech()
    if nxt is not None and eco.have(nxt["cost"]):
        return {"reasoning": f"Researching {nxt['name']} ({nxt['desc']}).",
                "actions": [{"action": "research"}]}

    # 3. expand to the nearest affordable patch, diversifying ore types
    affordable = [p for p in patches if sim.can_build_field(p)]
    if affordable:
        affordable.sort(key=lambda p: (ore_fields.get(p.ore, 0), _dist(p)))
        p = affordable[0]
        return field_action(p, f"Expanding to {p.ore.replace('_', ' ')} patch #{p.id} "
                               f"({int(_dist(p))} tiles out).")

    # 4. relieve a backed-up field with another train
    for f in sim.fields.values():
        if f.buffer >= f.buffer_cap * 0.85 and eco.have({"locomotive": 1, "cargo_wagon": balance.DEFAULT_WAGONS}):
            return {"reasoning": f"Field #{f.id} buffer backing up; adding a train.",
                    "actions": [{"action": "add_train", "field_id": f.id}]}

    # 5. scale home production with spare stock
    if eco.inv.get("assembler", 0) >= 2 and eco.assemblers < 16:
        return {"reasoning": "Scaling crafting: deploying an assembler.",
                "actions": [{"action": "build_assembler", "count": 1}]}
    if eco.inv.get("stone_furnace", 0) >= 4 and eco.furnaces < 40:
        return {"reasoning": "Scaling smelting: deploying a furnace.",
                "actions": [{"action": "build_furnace", "count": 1}]}

    return {"reasoning": "Stockpiling materials; no affordable expansion right now.",
            "actions": [{"action": "wait", "reason": "accumulating materials"}]}
