"""Pytest suite for AutoFactorio (headless; no window required).

Run:  .venv\\Scripts\\python -m pytest -q
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofactorio import balance
from autofactorio.config import Config
from autofactorio.engine.simulation import Simulation
from autofactorio.ai.director import Director


def _run(sim, director=None, seconds=60, dt=1 / 60):
    for _ in range(int(seconds / dt)):
        sim.tick(dt)
        if director is not None:
            director.update()


# ---- world / bootstrap ----------------------------------------------------
def test_starter_patches_discovered():
    sim = Simulation(Config())
    disc = sim.world.discovered_patches()
    ores = {p.ore for p in disc}
    assert "iron_ore" in ores and "coal" in ores


# ---- core economic loop ---------------------------------------------------
def test_loop_delivers_smelts_crafts():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    ok, msg = sim.build_field(iron.id)
    assert ok, msg
    _run(sim, seconds=180)
    assert sim.delivered_total > 0
    assert sim.economy.total_smelted > 0
    assert sim.economy.total_crafted > 0


def test_production_runs_at_60fps():
    """Regression: banked work must let recipes complete despite tiny per-tick budget."""
    eco = Simulation(Config()).economy
    eco.inv["iron_ore"] = 500
    before = eco.inv.get("iron_plate", 0)
    for _ in range(600):           # 10s at 60fps
        eco.update(1 / 60)
    assert eco.total_smelted > 0
    assert eco.inv.get("iron_plate", 0) != before


# ---- autonomous director --------------------------------------------------
def test_network_self_expands():
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    _run(sim, director, seconds=600)
    s = sim.stats()
    assert s["fields"] >= 3
    assert s["delivered"] > 500
    assert s["rail_tiles"] > 60
    assert s["stalled_trains"] == 0
    assert "coal" in {f.patch.ore for f in sim.fields.values()}


# ---- depleted-field lifecycle --------------------------------------------
def test_abandon_field_salvages_train():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    locos_before = sim.economy.inv.get("locomotive", 0)
    sim.build_field(iron.id)
    assert sim.economy.inv.get("locomotive", 0) == locos_before - 1
    assert len(sim.trains) == 1
    sim.fields[0].patch.reserve = 0               # deplete so it may be abandoned
    ok, msg = sim.abandon_field(0)
    assert ok, msg
    assert len(sim.trains) == 0
    assert len(sim.fields) == 0
    # locomotive + wagons salvaged back to stock
    assert sim.economy.inv.get("locomotive", 0) == locos_before
    assert sim.economy.inv.get("cargo_wagon", 0) >= balance.DEFAULT_WAGONS


def test_depleted_patch_is_auto_abandoned():
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    fld = sim.fields[0]
    fld.patch.reserve = 50          # nearly exhausted
    _run(sim, director, seconds=120)
    # the original field id 0 should have been retired and the patch drained
    assert 0 not in sim.fields
    assert fld.patch.depleted


# ---- save / load ----------------------------------------------------------
def test_save_load_roundtrip(tmp_path):
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    _run(sim, director, seconds=120)
    before = sim.stats()
    inv_before = dict(sim.economy.inv)
    path = str(tmp_path / "save.json")
    ok, _ = sim.save(path)
    assert ok

    sim2 = Simulation(Config(seed=cfg.seed))
    ok, _ = sim2.load(path)
    assert ok
    after = sim2.stats()
    assert after["fields"] == before["fields"]
    assert after["trains"] == before["trains"]
    assert after["delivered"] == before["delivered"]
    assert abs(after["time"] - before["time"]) < 1e-6
    assert dict(sim2.economy.inv) == inv_before
    # the loaded game must keep running cleanly
    d2 = Director(sim2, Config(seed=cfg.seed))
    _run(sim2, d2, seconds=60)
    assert sim2.stats()["delivered"] >= before["delivered"]


def test_load_rebuilds_world_on_seed_mismatch(tmp_path):
    cfg = Config(seed=4242)
    sim = Simulation(cfg)
    sim.build_field(next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore").id)
    _run(sim, seconds=30)
    path = str(tmp_path / "s.json")
    sim.save(path)
    other = Simulation(Config(seed=999))     # different seed
    ok, _ = other.load(path)
    assert ok and other.world.seed == 4242


# ---- tech research --------------------------------------------------------
def test_research_advances_and_applies():
    sim = Simulation(Config())
    tech0 = balance.TECHS[0]
    for k, v in tech0["cost"].items():
        sim.economy.inv[k] = v
    base = sim.research.drill_mult
    ok, msg = sim.research_next()
    assert ok, msg
    assert sim.research.level == 1
    assert sim.research.drill_mult > base       # tech 0 boosts drills


def test_research_lifts_existing_trains():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    t = next(iter(sim.trains.values()))
    base_cap = t.capacity
    for i in range(3):                            # through Cargo Capacity 1
        for k, v in balance.TECHS[i]["cost"].items():
            sim.economy.inv[k] = sim.economy.inv.get(k, 0) + v
        ok, _ = sim.research_next()
        assert ok
    assert sim.research.level == 3
    assert t.capacity > base_cap                  # capacity tech applied to the live train


def test_cannot_abandon_productive_field():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    ok, msg = sim.abandon_field(0)                # patch still has ore
    assert not ok
    assert 0 in sim.fields                        # field preserved


# ---- block-mutex collision safety ----------------------------------------
def test_two_trains_one_lane_never_share_a_block():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    sim.add_train(0)               # two trains on the same dedicated loop
    dt = 1 / 60
    for _ in range(int(240 / dt)):
        sim.tick(dt)
        seen: dict[int, int] = {}
        for t in sim.trains.values():
            for bid in t.locked:
                blk = sim.net.blocks.get(bid)
                # a locked block must be owned by exactly the train holding it
                assert blk.occupant == t.id
                assert bid not in seen, "two trains hold the same block!"
                seen[bid] = t.id
