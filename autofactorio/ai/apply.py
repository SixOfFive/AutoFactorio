"""Apply validated director actions to the simulation (main thread only).

Each action maps to a Simulation build method; results (success + message) are
returned for the comms console. Affordability/validity is enforced inside the
Simulation methods, so a bad pick fails gracefully with a message.
"""

from __future__ import annotations


def apply_actions(sim, actions: list[dict]) -> list[str]:
    results: list[str] = []
    for a in actions:
        name = a["action"]
        try:
            if name == "build_field":
                ok, msg = sim.build_field(a["patch_id"], a.get("tier"))
            elif name == "add_train":
                ok, msg = sim.add_train(a["field_id"])
            elif name == "abandon_field":
                ok, msg = sim.abandon_field(a["field_id"])
            elif name == "build_assembler":
                ok, msg = sim.build_assembler(max(1, a.get("count", 1)))
            elif name == "build_furnace":
                ok, msg = sim.build_furnace(max(1, a.get("count", 1)))
            elif name == "expand_drills":
                ok, msg = sim.expand_drills(a["field_id"], max(1, a.get("count", 2)))
            elif name == "research":
                ok, msg = sim.research_next()
            elif name == "wait":
                ok, msg = True, a.get("reason", "holding")
            else:
                ok, msg = False, f"unhandled action {name}"
        except Exception as e:  # never let a bad action crash the loop
            ok, msg = False, f"{name} error: {e}"
        results.append(("OK " if ok else "-- ") + msg)
    return results
