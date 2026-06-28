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
from autofactorio.engine.animals import Animal
from autofactorio.ai.director import Director


def _run(sim, director=None, seconds=60, dt=1 / 60):
    for _ in range(int(seconds / dt)):
        sim.tick(dt)
        if director is not None:
            director.update()


def _settle(sim, max_s=60):
    """Tick until robots have finished all pending construction jobs."""
    for _ in range(int(max_s / (1 / 60))):
        if not sim.jobs:
            return
        sim.tick(1 / 60)
    assert not sim.jobs, "construction jobs did not complete"


def _build_active(sim, patch_id, max_s=60):
    """Order a field and let a robot physically build it, then return."""
    ok, msg = sim.build_field(patch_id)
    assert ok, msg
    _settle(sim, max_s)


# ---- HUD tooltips ---------------------------------------------------------
def test_hud_tooltips_cover_bar_and_render():
    import unittest.mock as mock
    import pygame
    from autofactorio.ui.hud import Hud, INFO, _INV

    keys = {k for k, _ in _INV} | {"time", "fields", "trains", "rail_stat",
                                   "delivered", "robots", "animals", "tech",
                                   "speed", "director"}
    for k in keys:
        assert k in INFO, f"no tooltip for {k}"

    pygame.init()
    screen = pygame.Surface((1280, 720))
    f = pygame.font.SysFont("monospace", 14)
    hud = Hud(f, f, f)
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    hud.draw(screen, sim, director, False)
    assert hud._zones
    rect, _key = hud._zones[0]
    with mock.patch.object(pygame.mouse, "get_pos", return_value=rect.center):
        hud.draw_tooltip(screen)          # must not raise


def test_click_selects_base_shows_panel():
    from autofactorio.ui.app import App
    cfg = Config()
    cfg.llm.enabled = False
    cfg.display.width, cfg.display.height = 800, 600
    app = App(cfg)
    app.cam.center_on(0, 0)
    app.cam.zoom = 20.0
    app._pick((400, 300))                 # screen center maps to the home base
    assert app.selected == ("base", 0)
    app._draw()                           # base panel must render cleanly


def test_click_selects_unclaimed_patch():
    from autofactorio.ui.app import App
    cfg = Config()
    cfg.llm.enabled = False
    cfg.display.width, cfg.display.height = 800, 600
    app = App(cfg)
    p = next(pp for pp in app.sim.world.discovered_patches() if not pp.claimed)
    app.cam.center_on(p.cx, p.cy)
    app.cam.zoom = 20.0
    app._pick((400, 300))                 # screen center maps to the patch
    assert app.selected == ("patch", p.id)
    app._draw()                           # readout + highlight must render cleanly


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
def test_decommission_stores_train_then_robot_reclaims_track():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    locos_before = sim.economy.inv.get("locomotive", 0)
    _build_active(sim, iron.id)                      # robot lays the track first
    assert sim.economy.inv.get("locomotive", 0) == locos_before - 1
    assert len(sim.trains) == 1
    f = sim.fields[0]
    edges = list(f.edge_ids)
    f.patch.reserve = 0
    ok, _ = sim.abandon_field(0)
    assert ok and sim.fields[0].state == "recalling"
    assert len(sim.trains) == 1                    # NOT removed instantly
    assert all(e in sim.net.edges for e in edges)  # track NOT torn up yet
    # drive it: train returns home -> storage -> robot tears up track -> hauls
    # the salvage all the way home and deposits it
    for _ in range(int(600 / (1 / 60))):
        sim.tick(1 / 60)
        if 0 not in sim.fields and not any(r.dismantle_phase for r in sim.robots.values()):
            break
    assert 0 not in sim.fields                      # fully decommissioned
    assert all(e not in sim.net.edges for e in edges)             # track removed
    assert sim.economy.inv.get("locomotive", 0) >= locos_before   # train stored
    assert any("returned salvage to base" in e[1] for e in sim.events)  # rail/drills hauled back


def test_abandon_is_idempotent_and_non_destructive_at_start():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    f = sim.fields[0]
    edges = list(f.edge_ids)
    f.patch.reserve = 0
    ok, _ = sim.abandon_field(0)
    assert ok and f.state == "recalling"
    assert all(e in sim.net.edges for e in edges)   # nothing torn up immediately
    ok2, _ = sim.abandon_field(0)                    # repeated calls are no-ops
    assert ok2 and f.state == "recalling"


def test_depleted_patch_is_auto_decommissioned():
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    fld = sim.fields[0]
    fld.patch.reserve = 50          # nearly exhausted
    _run(sim, director, seconds=300)
    # the original field id 0 should have been fully decommissioned and drained
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


def test_save_load_preserves_construction_job(tmp_path):
    cfg = Config()
    sim = Simulation(cfg)
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    ok, _ = sim.build_field(iron.id)
    assert ok and sim.jobs and sim.fields[0].state == "constructing"
    path = str(tmp_path / "mid.json")
    sim.save(path)

    sim2 = Simulation(Config(seed=cfg.seed))
    ok, _ = sim2.load(path)
    assert ok
    assert len(sim2.jobs) == len(sim.jobs)
    assert sim2.fields[0].state == "constructing"
    assert any(not e.built for e in sim2.net.edges.values())   # ghost track preserved
    # resume: a robot finishes the build and the train is dispatched
    _settle(sim2, 60)
    assert sim2.fields[0].state == "active" and len(sim2.trains) == 1


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


# ---- animals & robots -----------------------------------------------------
def test_animals_spawn_in_fog():
    sim = Simulation(Config())
    _run(sim, seconds=90)
    assert len(sim.animals.list) > 0


def test_animal_dies_from_damage():
    sim = Simulation(Config())
    sim.animals.list[1] = Animal(1, 50, 50, herd=0, hp=20)
    died = sim.animals.hit(1, 25, by_robot=0, retaliate=True)
    assert died and 1 not in sim.animals.list


def test_robot_build_cap_and_replaceable():
    sim = Simulation(Config())            # starts with 2 robots, cap 3
    assert len(sim.robots) == 2
    assert sim.can_replace_robot()        # a spare already exists (2 robots)
    # no robot assembled in stock yet -> cannot deploy a new one
    assert not sim.can_build_robot()
    sim.economy.inv["robot"] = 2          # assembled and ready to deploy
    assert sim.can_build_robot()
    ok, _ = sim.build_robot()
    assert ok and len(sim.robots) == 3
    ok, _ = sim.build_robot()              # at cap (3) now
    assert not ok and len(sim.robots) == 3


def test_train_crushes_animal_and_takes_damage():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.state = "moving"
    head = t.car_poses()[0]
    sim.animals.list[1] = Animal(1, head[0], head[1], herd=0)
    hp_before = t.hp
    sim._crush_animals()
    assert 1 not in sim.animals.list
    assert t.hp < hp_before


def test_robot_repairs_damaged_train():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.hp = 10.0
    r = sim.robots.explorer()
    head = t.car_poses()[0]
    r.x, r.y = head[0], head[1]            # park the robot on the train
    for _ in range(int(3 / (1 / 60))):
        sim.robots.update(sim, 1 / 60)
    assert t.hp > 10.0


# ---- director connectivity (offline -> internal -> reconnect) ------------
def test_director_offline_then_reconnect():
    cfg = Config()                       # llm enabled by default
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    director.decisions = 1               # past the instant-kickstart first move

    n = len(sim.events)
    director._set_offline("HTTP 502 from gateway")
    assert director.online is False
    assert "retry" in director.status_text().lower()
    assert any("unreachable" in e[1].lower() for e in sim.events[n:])

    # while offline, decisions still flow via the internal heuristic (no thread)
    director._start()
    director._apply_ready()
    assert director.source == "auto"
    assert not director._busy

    # a successful reconnect probe resumes the AI director
    n = len(sim.events)
    director._probe_result = True
    director._check_reconnect()
    assert director.online is True
    assert any("reconnected" in e[1].lower() for e in sim.events[n:])


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
    _build_active(sim, iron.id)
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
    _build_active(sim, iron.id)
    ok, msg = sim.abandon_field(0)                # patch still has ore
    assert not ok
    assert 0 in sim.fields                        # field preserved


# ---- train-vs-train collision avoidance -----------------------------------
def test_train_cars_stay_connected_across_legs():
    import math as _m
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    # finish the current leg and depart onto the next one
    t.head_s = t.leg_len
    t.depart(sim.net)
    assert t.head_s == 0.0
    poses = t.car_poses()
    # cars must trail back (onto the previous leg), not pile up at the new start
    spread = _m.dist(poses[0][:2], poses[-1][:2])
    assert spread > balance.ENTITY_LEN, f"cars bunched at leg start (spread={spread:.2f})"
    for a, b in zip(poses, poses[1:]):
        assert _m.dist(a[:2], b[:2]) > balance.ENTITY_LEN * 0.5


def test_unload_takes_time_and_research_speeds_it():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.begin_leg(sim.net, 1)                 # the return leg ends at the home unload stop
    t.head_s = t.leg_len
    t.state = "waiting"

    t.cargo = {"iron_ore": 2000}
    before = sim.economy.inv.get("iron_ore", 0)
    sim._service_station(t, 1 / 60)
    base_moved = sim.economy.inv.get("iron_ore", 0) - before
    assert 0 < base_moved < 2000            # partial unload, not instant
    assert t.cargo_total() > 0              # still has cargo to unload

    sim.research.unload_mult = 4.0          # research speeds unloading
    t.cargo = {"iron_ore": 2000}
    before = sim.economy.inv.get("iron_ore", 0)
    sim._service_station(t, 1 / 60)
    fast_moved = sim.economy.inv.get("iron_ore", 0) - before
    assert fast_moved > base_moved


def test_train_waits_for_obstacle_ahead():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.state = "moving"
    t.fuel_seconds = 100.0
    hx, hy, _, _ = t.car_poses()[0]
    before = t.head_s
    t.update_movement(1 / 60, sim.net, obstacles=[(hx, hy)])   # obstacle right on us
    assert t.waiting_for_train
    assert t.head_s == before                                   # did not advance
    # with no obstacle it moves
    t.update_movement(1 / 60, sim.net, obstacles=[])
    assert t.head_s > before


# ---- field lifecycle: proportional depletion + track reclamation ----------
def test_farther_field_depletes_nearer_ones():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    sim.build_field(iron.id)
    near = sim.fields[0].patch
    before = near.reserve
    sim._deplete_nearer_fields(new_fid=999, new_dist=120.0)
    assert near.reserve < before


def test_explorer_spiral_restarts_from_home():
    from autofactorio.engine.robots import Robot
    r = Robot(0, 0.0, 0.0, explorer=True)
    prev = r.radius
    restarted = False
    for _ in range(3000):
        r._advance_spiral()
        if r.radius < prev - 1.0:        # radius dropped sharply -> spiral reset
            restarted = True
            break
        prev = r.radius
    assert restarted


# ---- block-mutex collision safety ----------------------------------------
def test_two_trains_one_lane_never_share_a_block():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    sim.add_train(0)               # second loop to the same field
    _settle(sim)                   # let a robot lay the second loop
    assert len(sim.trains) == 2
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
