"""Heuristic director used when the LLM gateway is disabled or unreachable.

Emits the same {"reasoning", "actions"} shape as the LLM so the apply path is
identical. Plays an AGGRESSIVE industrial superpower: every turn it does as much as
the stockpile can pay for - secure essentials, relieve full storage, research,
claim MANY patches at once, add trains to busy fields, and deploy the whole bench of
stockpiled factories + drills to keep processing capacity racing ahead. A local
inventory budget keeps the multi-action plan affordable (so it doesn't queue builds
it can't pay for), and a backlog guard avoids piling up more fields than the robots
can lay.
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
    tier = sim.choose_tier()
    stats = sim.stats()

    budget = dict(eco.inv)                  # local copy so the multi-action plan stays affordable
    actions: list[dict] = []
    why: list[str] = []

    def afford(cost: dict) -> bool:
        return all(budget.get(k, 0) >= v for k, v in cost.items())

    def spend(cost: dict) -> None:
        for k, v in cost.items():
            budget[k] = budget.get(k, 0) - v

    # 0. decommission EVERY exhausted field (free; recovers each train)
    for f in list(sim.fields.values()):
        if f.patch.depleted and getattr(f, "state", "active") == "active":
            actions.append({"action": "abandon_field", "field_id": f.id})
            why.append(f"retire depleted #{f.id}")

    # 1. deploy a robot when there's a real need (backlog / wildlife / repairs / too few)
    if sim.can_build_robot() and afford({"robot": 1}) and (
            len(sim.jobs) > len(sim.robots) or stats["animals"] > 6
            or stats["damaged_trains"] > 0 or len(sim.robots) < 2):
        actions.append({"action": "build_robot"})
        spend({"robot": 1})
        why.append("robot")

    # 2. relieve EVERY backed-up resource we can pay for (a full silo stalls the economy)
    for _frac, item in sorted(((eco.fill_fraction(k), k) for k in eco.caps
                               if k != "science_pack"
                               and eco.fill_fraction(k) >= balance.STORAGE_RELIEF_FRACTION
                               and eco.caps[k] < balance.STORAGE_CAP_START[k] * balance.STORAGE_MAX_MULT),
                              reverse=True):
        if not afford(balance.STORAGE_COST):
            break
        actions.append({"action": "build_storage", "item": item})
        spend(balance.STORAGE_COST)
        why.append(f"{balance.DISPLAY_NAME.get(item, item)} storage")

    # 3. research the moment it's affordable (it compounds the WHOLE empire)
    nxt = sim.research.next_tech()
    if nxt is not None and afford(nxt["cost"]):
        actions.append({"action": "research"})
        spend(nxt["cost"])
        why.append(f"research {nxt['name']}")

    # 4. EXPAND HARD: secure missing essential ores, then claim as many affordable
    #    patches as the stockpile can pay for - capped only by a backlog guard so the
    #    robots aren't buried under more track than they can lay.
    claimed: set[int] = set()
    backlog_room = len(sim.robots) + 2 - len(sim.jobs)

    def try_claim(p, tag: str) -> None:
        nonlocal backlog_room
        if backlog_room <= 0 or p.id in claimed:
            return
        if not (p.discovered and not p.claimed and not p.depleted):
            return
        cost = sim.field_cost(p, tier)
        if afford(cost):
            actions.append({"action": "build_field", "patch_id": p.id})
            spend(cost)
            claimed.add(p.id)
            backlog_room -= 1
            why.append(tag)

    for ore in ("iron_ore", "copper_ore", "coal", "stone"):
        if ore_fields.get(ore, 0) == 0:
            p = next((p for p in patches if p.ore == ore), None)
            if p:
                try_claim(p, f"secure {ore.replace('_', ' ')}")
    # coal now powers the whole base (and trains) - grab MORE coal under fuel pressure
    if eco.inv.get("coal", 0) < balance.FUEL_CRITICAL * 4 or eco.power_factor < 0.95:
        p = next((p for p in patches if p.ore == "coal" and p.id not in claimed), None)
        if p:
            try_claim(p, "more coal for power")
    for p in sorted(patches, key=lambda q: (ore_fields.get(q.ore, 0), _dist(q))):
        try_claim(p, f"expand {p.ore.replace('_', ' ')} #{p.id}")

    # (We deliberately don't pile a SECOND train onto a field's loop - one train hauls
    #  far faster than a field mines, so a single train per field always keeps up, and
    #  it avoids two trains contending for one loop's home stop. Throughput scales by
    #  claiming MORE fields, above, not by doubling up trains.)

    # 6. SCALE PROCESSING on demand: if raw ore is backing up, smelting is the
    #    bottleneck -> add furnaces; if plates are backing up, crafting is -> add
    #    assemblers. Ramp in modest BATCHES toward a generous field-relative ceiling so
    #    capacity tracks ore intake (and keeps GROWING as the empire grows) without one
    #    delivery burst ballooning the base to thousands of idle furnaces.
    nf = max(1, len(sim.fields))
    raw_backing = any(eco.fill_fraction(o) >= 0.7 for o in ("iron_ore", "copper_ore", "coal", "stone"))
    plate_backing = any(eco.fill_fraction(o) >= 0.7 for o in ("iron_plate", "copper_plate", "steel_plate"))
    if raw_backing and eco.furnaces < nf * 16:
        n = min(budget.get("stone_furnace", 0), 6, nf * 16 - eco.furnaces)
        if n >= 1:
            actions.append({"action": "build_furnace", "count": n})
            why.append(f"+{n} furnaces (ore backing up)")
    if plate_backing and eco.assemblers < nf * 10:
        n = min(budget.get("assembler", 0), 4, nf * 10 - eco.assemblers)
        if n >= 1:
            actions.append({"action": "build_assembler", "count": n})
            why.append(f"+{n} assemblers (plates backing up)")

    # 7. pour spare drills into productive fields to mine faster
    drill_item = "electric_drill" if tier == "electric" else "burner_drill"
    spare_drills = budget.get(drill_item, 0)
    for f in sim.fields.values():
        if spare_drills < 2:
            break
        if f.patch.depleted or getattr(f, "state", "active") != "active":
            continue
        actions.append({"action": "expand_drills", "field_id": f.id, "count": 2})
        spare_drills -= 2
        why.append(f"+drills #{f.id}")

    if not actions:
        return {"reasoning": "Stockpiling materials; no affordable move yet.",
                "actions": [{"action": "wait", "reason": "accumulating materials"}]}
    return {"reasoning": "; ".join(why[:8]), "actions": actions}
