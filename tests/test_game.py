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


def test_moving_train_reveals_fog():
    """A running train clears fog around each of its cars (rails are sightlines)."""
    import numpy as np

    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)                       # robot lays track, train dispatched
    # advance until the train is actually moving along the corridor
    for _ in range(int(30 / (1 / 60))):
        sim.tick(1 / 60)
        t = next(iter(sim.trains.values()))
        if t.state == "moving" and t.car_poses():
            break
    t = next(iter(sim.trains.values()))
    assert t.state == "moving" and t.car_poses()
    # black out the whole map, then tick once: only the train (and far-off scout)
    # can re-light tiles, so any cleared tile under a car proves the train did it.
    sim.world.explored[:] = 0
    cars = t.car_poses()
    sim.tick(1 / 60)
    assert any(sim.world.is_explored(int(round(x)), int(round(y)))
               for (x, y, _a, _k) in cars), "train did not clear fog around its cars"


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


def test_coal_converts_to_processed_fuels():
    """Surplus coal is converted up the fuel chain (coal -> solid -> rocket), while
    a coal reserve is kept for direct burning and rocket fuel needs its tech."""
    sim = Simulation(Config())
    sim.research.level = balance.ROCKET_FUEL_TECH      # unlock rocket fuel
    sim._sync_research()
    eco = sim.economy
    eco.inv["coal"] = 8000
    eco.inv["steel_plate"] = 200
    for _ in range(int(60 / (1 / 60))):
        eco.update(1 / 60)
    assert eco.inv.get("solid_fuel", 0) > 0
    assert eco.inv.get("rocket_fuel", 0) > 0
    assert eco.inv["coal"] >= balance.FUEL_COAL_RESERVE   # reserve kept for burning


def test_rocket_fuel_needs_its_tech():
    sim = Simulation(Config())
    sim.research.level = 0                              # rocket fuel NOT unlocked
    sim._sync_research()
    eco = sim.economy
    eco.inv["coal"] = 8000
    eco.inv["steel_plate"] = 200
    for _ in range(int(40 / (1 / 60))):
        eco.update(1 / 60)
    assert eco.inv.get("solid_fuel", 0) > 0            # basic fuel always available
    assert eco.inv.get("rocket_fuel", 0) == 0          # rocket fuel gated by research


def test_best_available_fuel_prefers_denser():
    eco = Simulation(Config()).economy
    eco.inv["coal"] = 100
    assert eco.best_available_fuel()[0] == "coal"
    eco.inv["solid_fuel"] = 10
    assert eco.best_available_fuel()[0] == "solid_fuel"
    eco.inv["rocket_fuel"] = 1
    fuel, burn = eco.best_available_fuel()
    assert fuel == "rocket_fuel"
    assert burn == balance.FUEL_BURN["rocket_fuel"]    # efficiency mult is 1.0 at L0


def test_better_fuel_gives_longer_train_range():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    eco = sim.economy
    # coal-only refuel tops the loco to a short range
    eco.inv.clear()
    eco.inv["coal"] = 1000
    t.fuel_seconds = 0.0
    sim._refuel(t)
    coal_range = t.fuel_seconds
    # rocket fuel tops the same loco to a much longer range
    eco.inv.clear()
    eco.inv["rocket_fuel"] = 1000
    t.fuel_seconds = 0.0
    sim._refuel(t)
    rocket_range = t.fuel_seconds
    assert rocket_range > coal_range * 5               # far more run-seconds per loco


def test_fuel_efficiency_research_scales_burn():
    sim = Simulation(Config())
    assert sim.research.fuel_efficiency == 1.0         # baseline at L0
    sim.research.level = 500
    assert sim.research.fuel_efficiency > 1.5          # research makes fuel last longer
    sim._sync_research()
    assert sim.economy.research_fuel_mult == sim.research.fuel_efficiency
    assert sim.economy.rocket_fuel_unlocked is True


def test_robot_refuels_stalled_train():
    """A train that runs out of fuel must be rescued: a robot hauls coal from base
    and pours it in so the dead train (which blocks track) can move again."""
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    sim.economy.inv["coal"] = 500          # base has fuel to deliver
    t.fuel_seconds = 0.0                    # strand it
    sim.tick(1 / 60)
    assert t.stalled                        # it is now dead on the track
    rescued = False
    for _ in range(int(240 / (1 / 60))):
        sim.tick(1 / 60)
        if not t.stalled and t.fuel_seconds > 0:
            rescued = True
            break
    assert rescued, "robot never refuelled the stalled train"
    assert any("refuelled stalled train" in e[1] for e in sim.events)


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
    nxt = sim.research.next_tech()
    for k, v in nxt["cost"].items():
        sim.economy.inv[k] = v
    base = sim.research.drill_mult
    ok, msg = sim.research_next()
    assert ok, msg
    assert sim.research.level == 1
    assert sim.research.drill_mult > base       # every level compounds mining


def test_research_lifts_existing_trains():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    base_cap = t.capacity
    for _ in range(8):                            # several levels grow wagon capacity
        nxt = sim.research.next_tech()
        for k, v in nxt["cost"].items():
            sim.economy.inv[k] = sim.economy.inv.get(k, 0) + v
        ok, _ = sim.research_next()
        assert ok
    assert sim.research.level == 8
    assert t.capacity > base_cap                  # capacity scaling applied to the live train


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

    sim.research.level = 150                # deep research speeds unloading (~4x)
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


# ---- signal-based traffic control: junction interlock + priority ----------
def test_traffic_priority_loaded_and_recall_beat_empty():
    """Right-of-way policy: loaded or recalled trains outrank empty outbound ones
    (lower key = higher priority), with id as a strict tiebreak (=> no cycles)."""
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.cargo.clear()
    t.recall = False
    empty_key = t.traffic_priority()
    t.cargo["iron_ore"] = 500                         # now loaded
    loaded_key = t.traffic_priority()
    t.cargo.clear()
    t.recall = True                                   # being recalled to storage
    recall_key = t.traffic_priority()
    assert loaded_key < empty_key                     # loaded gets right of way
    assert recall_key < empty_key                     # recall clears out first
    assert empty_key[1] == t.id                       # id is the tiebreak field


def test_no_train_collisions_across_a_busy_run():
    """Home loops fan out from a ring (so their track never converges at the centre)
    and every train hard-stops before overlapping another car, so across a busy
    multi-field run NO two trains ever physically overlap, while traffic still flows
    and never permanently stalls."""
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    director = Director(sim, cfg)
    dt = 1 / 60
    overlaps = 0
    thr = (balance.ENTITY_WIDTH * 0.9) ** 2
    for _ in range(int(360 / dt)):
        sim.tick(dt)
        director.update()
        poses = [t.car_poses() for t in sim.trains.values()]
        for i in range(len(poses)):
            for j in range(i + 1, len(poses)):
                for (ax, ay, _a, _k) in poses[i]:
                    if any((ax - bx) ** 2 + (ay - by) ** 2 < thr for (bx, by, _b, _k2) in poses[j]):
                        overlaps += 1
                        break
    assert overlaps == 0, f"trains overlapped {overlaps} times (collisions)"
    s = sim.stats()
    assert s["delivered"] > 500
    assert s["stalled_trains"] == 0                   # no permanent stall


def test_many_loops_keep_flowing_without_permanent_jam():
    """Many loops to spread-out fields must keep delivering (no permanent gridlock)
    and never overlap - the home loops fan out and the anti-deadlock guarantees the
    network can't freeze."""
    import math
    sim = Simulation(Config())
    sim.world.explored[:] = 1
    for p in sim.world.patches:
        p.discovered = True
    chosen, used = [], []
    for p in sorted(sim.world.claimable_patches(), key=lambda p: math.hypot(p.cx, p.cy)):
        a = math.atan2(p.cy, p.cx)
        if all(abs((a - b + math.pi) % (2 * math.pi) - math.pi) > math.radians(25) for b in used):
            chosen.append(p)
            used.append(a)
        if len(chosen) >= 8:
            break
    for p in chosen:
        for k in ("rail", "rail_signal", "chain_signal", "train_stop", "locomotive",
                  "cargo_wagon", "electric_drill", "iron_plate", "steel_plate", "stone", "coal"):
            sim.economy.inv[k] = 1_000_000
        sim.build_field(p.id)
    _settle(sim, max_s=120)
    dt = 1 / 60
    for _ in range(int(60 / dt)):                 # warm up
        sim.tick(dt)
    mid = sim.delivered_total
    overlaps = 0
    thr = (balance.ENTITY_WIDTH * 0.9) ** 2
    for step in range(int(120 / dt)):
        sim.tick(dt)
        if step % 5 == 0:
            poses = [t.car_poses() for t in sim.trains.values()]
            for i in range(len(poses)):
                for j in range(i + 1, len(poses)):
                    if any((ax - bx) ** 2 + (ay - by) ** 2 < thr
                           for (ax, ay, _a, _k) in poses[i] for (bx, by, _b, _l) in poses[j]):
                        overlaps += 1
    assert sim.delivered_total > mid + 1000, "network stopped delivering (permanent jam)"
    assert overlaps == 0, f"trains overlapped {overlaps} times"


def test_signal_aspect_goes_red_when_block_occupied():
    """Live signal aspects: a signal reads red while a train sits on the block it
    guards (so the rendered signals reflect real occupancy)."""
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    saw_red = False
    for _ in range(int(120 / (1 / 60))):
        sim.tick(1 / 60)
        if any(s.aspect == "red" for s in sim.net.signals.values()):
            saw_red = True
            break
    assert saw_red, "no signal turned red while a train occupied a block"


# ---- per-resource storage caps --------------------------------------------
def test_storage_add_clamps_to_cap_and_uncapped_passes():
    eco = Simulation(Config()).economy
    eco.inv["coal"] = eco.caps["coal"] - 5
    took = eco.add("coal", 100)
    assert took == 5                                   # only what fits is stored
    assert eco.inv["coal"] == eco.caps["coal"]
    assert eco.add("coal", 50) == 0                    # already full
    # transient intermediates are uncapped
    assert "iron_gear" not in eco.caps
    assert eco.add("iron_gear", 1000) == 1000


def test_build_storage_is_per_resource_and_costs_materials():
    sim = Simulation(Config())
    eco = sim.economy
    assert eco.have(balance.STORAGE_COST)             # starting stock can afford one
    coal_before = eco.caps["coal"]
    iron_before = eco.caps["iron_ore"]
    cost_item = next(iter(balance.STORAGE_COST))       # whatever storage is priced in
    spent_before = eco.inv.get(cost_item, 0)
    ok, _ = sim.build_storage("coal")
    assert ok
    assert eco.caps["coal"] == coal_before + balance.STORAGE_CAP_STEP["coal"]
    assert eco.caps["iron_ore"] == iron_before        # other resources unaffected
    assert eco.inv[cost_item] == spent_before - balance.STORAGE_COST[cost_item]
    # unaffordable -> fails cleanly, cap unchanged
    eco.inv[cost_item] = 0
    cap_now = eco.caps["coal"]
    ok, msg = sim.build_storage("coal")
    assert not ok and eco.caps["coal"] == cap_now


def test_full_storage_backpressures_unload():
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.begin_leg(sim.net, 1)                            # return leg -> home unload stop
    t.head_s = t.leg_len
    t.state = "waiting"
    eco = sim.economy
    eco.inv["iron_ore"] = eco.caps["iron_ore"]        # storage already full
    t.cargo = {"iron_ore": 1000}
    sim._service_station(t, 1 / 60)
    assert t.cargo.get("iron_ore", 0) == 1000          # nothing could be unloaded
    assert eco.inv["iron_ore"] == eco.caps["iron_ore"]  # cap not exceeded


def test_smelting_halts_when_plate_storage_full():
    eco = Simulation(Config()).economy
    eco.inv["iron_plate"] = eco.caps["iron_plate"]    # plate storage full
    eco.inv["iron_ore"] = 100
    eco.inv["copper_ore"] = 0
    eco._smelt_bank = 50.0
    eco._smelt()
    assert eco.inv["iron_ore"] == 100                  # iron smelting halted (no room)
    assert eco.inv["iron_plate"] <= eco.caps["iron_plate"]


def test_fallback_builds_storage_when_backed_up():
    from autofactorio.ai import fallback
    from autofactorio.ai.report import build_report
    cfg = Config()
    cfg.llm.enabled = False
    sim = Simulation(cfg)
    # nothing to expand to (so the heuristic reaches the storage-relief rule) and
    # plenty of build materials on hand
    for p in sim.world.patches:
        p.claimed = True
    # enough to afford a storage build, but kept below their own caps so COAL is
    # unambiguously the fullest resource the relief rule should pick
    sim.economy.inv["stone"] = 300
    sim.economy.inv["iron_plate"] = 200
    sim.economy.inv["coal"] = sim.economy.cap_of("coal")     # coal storage full
    dec = fallback.decide(sim, build_report(sim))
    acts = dec["actions"]
    assert any(a["action"] == "build_storage" and a.get("item") == "coal" for a in acts), acts
    # and the action actually raises that resource's base cap by one step
    before = sim.economy.caps["coal"]
    ok, _ = sim.build_storage("coal")
    assert ok and sim.economy.caps["coal"] == before + balance.STORAGE_CAP_STEP["coal"]


def test_save_load_preserves_storage_caps():
    import tempfile, os
    sim = Simulation(Config())
    sim.economy.caps["coal"] = 9999
    sim.economy.caps["iron_plate"] = 1234
    path = os.path.join(tempfile.gettempdir(), "af_storage_caps.sav")
    ok, _ = sim.save(path)
    assert ok
    sim2 = Simulation(Config())
    ok, _ = sim2.load(path)
    assert ok
    assert sim2.economy.caps["coal"] == 9999
    assert sim2.economy.caps["iron_plate"] == 1234


def test_recalled_train_stores_even_when_storage_full():
    """Regression: a recalled train whose storage is full must still go into
    storage (after the idle wait) instead of circling the depleted field forever
    and blocking decommission."""
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    t.recall = True
    t.begin_leg(sim.net, 1)                            # return leg -> home unload stop
    t.head_s = t.leg_len
    t.state = "waiting"
    sim.economy.inv["iron_ore"] = sim.economy.caps["iron_ore"]   # storage full
    t.cargo = {"iron_ore": 500}                        # undeliverable cargo aboard
    tid = t.id
    for _ in range(int(8 / (1 / 60))):                 # > WAIT_IDLE seconds
        if tid not in sim.trains:
            break
        sim._service_station(t, 1 / 60)
    assert tid not in sim.trains, "recalled train never stored despite full storage"


def test_store_train_never_loses_rolling_stock_at_cap():
    """Regression: returning a train when loco/wagon storage is full must not
    vanish the rolling stock (you can always park a train you own)."""
    sim = Simulation(Config())
    iron = next(p for p in sim.world.discovered_patches() if p.ore == "iron_ore")
    _build_active(sim, iron.id)
    t = next(iter(sim.trains.values()))
    w = t.wagons
    eco = sim.economy
    eco.inv["locomotive"] = eco.caps["locomotive"]    # loco storage already full
    eco.inv["cargo_wagon"] = eco.caps["cargo_wagon"]
    loco_before = eco.inv["locomotive"]
    wagon_before = eco.inv["cargo_wagon"]
    sim._store_train(t)
    assert eco.inv["locomotive"] == loco_before + 1   # conserved (over-cap allowed)
    assert eco.inv["cargo_wagon"] == wagon_before + w


def test_load_clamps_inventory_to_caps():
    import tempfile, os
    sim = Simulation(Config())
    sim.economy.inv["coal"] = sim.economy.caps["coal"] + 5000   # over-cap on disk
    path = os.path.join(tempfile.gettempdir(), "af_overcap.sav")
    ok, _ = sim.save(path)
    assert ok
    sim2 = Simulation(Config())
    ok, _ = sim2.load(path)
    assert ok
    assert sim2.economy.inv["coal"] == sim2.economy.caps["coal"]


def test_storage_step_below_start_so_growth_is_gradual():
    """A single storage build must add less than the resource's starting cap (so
    capacity grows gradually, never doubling in one build)."""
    for item, start in balance.STORAGE_CAP_START.items():
        step = balance.STORAGE_CAP_STEP.get(item, 0)
        assert 0 < step < start, f"{item} step {step} not < start {start}"


# ---- timer / autosave-autoload / new game ---------------------------------
def test_choose_startup_load_precedence():
    from run import choose_startup_load
    present = {"/save.json", "/auto.json"}
    exists = lambda p: p in present
    # explicit --load wins
    assert choose_startup_load("/save.json", False, None, "/auto.json", exists) == "/save.json"
    # a missing explicit load falls through to the autosave
    assert choose_startup_load("/missing.json", False, None, "/auto.json", exists) == "/auto.json"
    # --new ignores the autosave
    assert choose_startup_load(None, True, None, "/auto.json", exists) is None
    # a fixed --seed starts fresh
    assert choose_startup_load(None, False, 42, "/auto.json", exists) is None
    # default: resume the autosave when present
    assert choose_startup_load(None, False, None, "/auto.json", exists) == "/auto.json"
    # ...but a fresh game when there is none
    assert choose_startup_load(None, False, None, "/nope.json", exists) is None


def test_new_game_resets_timer_and_resources():
    from autofactorio.ui.app import App
    cfg = Config()
    cfg.llm.enabled = False
    cfg.display.width, cfg.display.height = 800, 600
    app = App(cfg)
    for _ in range(int(20 / (1 / 60))):       # let the timer and economy advance
        app.sim.tick(1 / 60)
    assert app.sim.time > 0
    fresh_iron = Simulation(Config()).economy.inv.get("iron_plate", 0)
    app.sim.economy.inv["iron_plate"] = 999999
    old_sim = app.sim
    app._new_game()
    assert app.sim is not old_sim             # a brand-new simulation
    assert app.sim.time == 0.0                # timer reset
    assert len(app.sim.fields) == 0           # back to the starting layout
    assert app.sim.economy.inv.get("iron_plate", 0) == fresh_iron   # resources reset


def test_autosave_path_roundtrip_resumes_timer():
    import tempfile, os
    from autofactorio.engine.simulation import Simulation as Sim
    sim = Sim(Config())
    for _ in range(int(15 / (1 / 60))):
        sim.tick(1 / 60)
    elapsed = sim.time
    assert elapsed > 0
    path = os.path.join(tempfile.gettempdir(), "af_autosave_test.json")
    ok, _ = sim.save(path)
    assert ok
    resumed = Sim(Config())
    assert resumed.time == 0.0
    ok, _ = resumed.load(path)
    assert ok
    assert abs(resumed.time - elapsed) < 1e-6   # the running timer carries over
