"""Headless engine smoke test: bootstrap a field, run the sim, assert the
mine -> train -> home loop actually moves ore and the economy produces goods.

Run:  .venv\\Scripts\\python tests\\smoke_engine.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofactorio import balance
from autofactorio.config import Config
from autofactorio.engine.simulation import Simulation


def main() -> int:
    cfg = Config()
    sim = Simulation(cfg)

    # The two guaranteed starter patches should be discovered at spawn.
    disc = sim.world.discovered_patches()
    print(f"discovered at start: {[(p.id, p.ore, (p.cx, p.cy)) for p in disc]}")
    assert disc, "no starter patches discovered at spawn"

    iron = next((p for p in disc if p.ore == "iron_ore"), disc[0])
    ok, msg = sim.build_field(iron.id)
    print("build_field:", ok, msg)
    assert ok, msg
    assert sim.trains, "no train created"

    # run ~3 minutes of sim time at dt=1/60
    dt = 1 / 60
    for _ in range(int(180 / dt)):
        sim.tick(dt)

    s = sim.stats()
    print("stats:", s)
    inv = sim.economy.inv
    snapshot = {k: inv[k] for k in ("iron_ore", "iron_plate", "iron_gear",
                                    "electronic_circuit", "rail", "coal") if inv.get(k)}
    print("inventory sample:", snapshot)
    print(f"economy: smelted={sim.economy.total_smelted} crafted={sim.economy.total_crafted} "
          f"furnaces={sim.economy.furnaces} assemblers={sim.economy.assemblers}")
    train = next(iter(sim.trains.values()))
    print(f"train#{train.id}: state={train.state} leg={train.cur_leg} "
          f"head_s={train.head_s:.1f}/{train.leg_len:.1f} cargo={train.cargo} "
          f"fuel={train.fuel_seconds:.1f} stalled={train.stalled}")

    assert s["delivered"] > 0, "no ore delivered home — loop is broken"
    assert sim.economy.total_smelted > 0, "furnaces never smelted any ore"
    assert sim.economy.total_crafted > 0, "assemblers never crafted anything"
    assert inv.get("rail", 0) > balance.STARTING_INVENTORY["rail"] - 30, "rail stock collapsed"
    print("\nSMOKE OK: ore delivered, smelted, and crafted into goods.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
