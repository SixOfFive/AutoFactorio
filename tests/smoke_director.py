"""Headless test of the autonomous loop: heuristic director + sim, no UI, no LLM.
Verifies the network self-expands (multiple fields, growing rail + deliveries).

Run:  .venv\\Scripts\\python tests\\smoke_director.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofactorio.config import Config
from autofactorio.engine.simulation import Simulation
from autofactorio.ai.director import Director


def main() -> int:
    cfg = Config()
    cfg.llm.enabled = False           # force heuristic director
    sim = Simulation(cfg)
    director = Director(sim, cfg)

    dt = 1 / 60
    minutes = 12
    for step in range(int(minutes * 60 / dt)):
        sim.tick(dt)
        director.update()

    s = sim.stats()
    print("final stats:", s)
    print(f"decisions made: {director.decisions}")
    ores = sorted({f.patch.ore for f in sim.fields.values()})
    print(f"field ore types: {ores}")
    print("last 12 events:")
    for t, e in sim.events[-12:]:
        print(f"  [{int(t):4d}s] {e}")

    assert s["fields"] >= 3, f"network barely grew (fields={s['fields']})"
    assert s["delivered"] > 500, f"too little ore delivered ({s['delivered']})"
    assert s["rail_tiles"] > 60, f"rail network did not grow ({s['rail_tiles']})"
    assert "coal" in ores, "director never secured a coal field"
    assert s["stalled_trains"] == 0, "trains stalled out of fuel"
    print("\nDIRECTOR SMOKE OK: the network self-expanded and kept trains fueled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
