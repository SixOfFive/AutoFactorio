"""All game-balance numbers in one place (pure data, no logic).

Sourced from the Factorio research brief: 4 raw resources, finite patches,
generic smelt/craft recipe tables, train + fuel model, world-gen params.
Tweak here to rebalance; nothing else hard-codes these.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
RAW_ORES = ["iron_ore", "copper_ore", "coal", "stone"]

# Smeltables: ore/intermediate -> product, with a base time (seconds at 1x furnace).
SMELT_RECIPES = {
    "iron_plate":   {"in": {"iron_ore": 1},   "out": {"iron_plate": 1},   "time": 3.2},
    "copper_plate": {"in": {"copper_ore": 1}, "out": {"copper_plate": 1}, "time": 3.2},
    "stone_brick":  {"in": {"stone": 2},       "out": {"stone_brick": 1},  "time": 3.2},
    "steel_plate":  {"in": {"iron_plate": 5}, "out": {"steel_plate": 1},  "time": 6.0},
}
FURNACE_SPEED = {"stone": 1.0, "electric": 2.0}   # effective time = recipe.time / speed

# Assembler recipes (intermediates + buildables). Output counts matter: several
# craft 2 at a time, so never assume 1:1.
RECIPES = {
    # intermediates
    "iron_stick":         {"in": {"iron_plate": 1},                        "out": {"iron_stick": 2},         "time": 0.5},
    "iron_gear":          {"in": {"iron_plate": 2},                        "out": {"iron_gear": 1},          "time": 0.5},
    "copper_cable":       {"in": {"copper_plate": 1},                      "out": {"copper_cable": 2},       "time": 0.5},
    "electronic_circuit": {"in": {"iron_plate": 1, "copper_cable": 3},     "out": {"electronic_circuit": 1}, "time": 0.5},
    "engine_unit":        {"in": {"iron_gear": 1, "steel_plate": 1, "iron_plate": 2}, "out": {"engine_unit": 1}, "time": 2.0},
    # research currency: the factory makes science from surplus; research spends it
    "science_pack":       {"in": {"electronic_circuit": 1, "iron_plate": 1, "copper_plate": 1}, "out": {"science_pack": 1}, "time": 1.0},
    # buildables
    "rail":          {"in": {"iron_stick": 1, "steel_plate": 1, "stone": 1},                       "out": {"rail": 2},          "time": 0.5},
    "rail_signal":   {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"rail_signal": 1},   "time": 0.5},
    "chain_signal":  {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"chain_signal": 1},  "time": 0.5},
    "train_stop":    {"in": {"electronic_circuit": 5, "iron_plate": 6, "iron_stick": 6, "steel_plate": 3}, "out": {"train_stop": 1}, "time": 0.5},
    "electric_drill":{"in": {"electronic_circuit": 3, "iron_gear": 5, "iron_plate": 10},           "out": {"electric_drill": 1},"time": 2.0},
    "stone_furnace": {"in": {"stone": 5},                                                          "out": {"stone_furnace": 1}, "time": 0.5},
    "assembler":     {"in": {"electronic_circuit": 3, "iron_gear": 5, "iron_plate": 9},            "out": {"assembler": 1},     "time": 0.5},
    # Rolling stock cheapened vs vanilla (loco was 20 engine units) so a trickle
    # economy can actually afford to expand - the whole point is watchable growth.
    "locomotive":    {"in": {"electronic_circuit": 4, "engine_unit": 6, "steel_plate": 12},        "out": {"locomotive": 1},    "time": 2.0},
    "cargo_wagon":   {"in": {"iron_gear": 6, "iron_plate": 12, "steel_plate": 8},                  "out": {"cargo_wagon": 1},   "time": 1.0},
    "robot":         {"in": {"electronic_circuit": 3, "iron_gear": 4, "steel_plate": 3},           "out": {"robot": 1},         "time": 3.0},
}

# Friendly display names + which sprite represents an item on the map (if any).
DISPLAY_NAME = {
    "iron_ore": "Iron ore", "copper_ore": "Copper ore", "coal": "Coal", "stone": "Stone",
    "iron_plate": "Iron plate", "copper_plate": "Copper plate", "steel_plate": "Steel plate",
    "stone_brick": "Stone brick", "iron_stick": "Iron stick", "iron_gear": "Iron gear",
    "copper_cable": "Copper cable", "electronic_circuit": "Circuit", "engine_unit": "Engine",
    "rail": "Rail", "rail_signal": "Signal", "chain_signal": "Chain signal",
    "train_stop": "Train stop", "electric_drill": "Electric drill", "burner_drill": "Burner drill",
    "stone_furnace": "Furnace", "assembler": "Assembler", "locomotive": "Locomotive",
    "cargo_wagon": "Cargo wagon", "science_pack": "Science", "robot": "Robot",
}

# ---------------------------------------------------------------------------
# Mining / smelting rates
# ---------------------------------------------------------------------------
DRILL_RATE = {"burner": 0.8, "electric": 2.0}     # ore/sec per drill (arcade-tuned for pace)
DEFAULT_FIELD_DRILLS = 4                           # drills auto-placed per new field
DEFAULT_FIELD_FURNACES = 0                         # smelting happens at home, not the field

# Patch default reserves by ore type (finite -> forces expansion).
PATCH_RESERVE = {"iron_ore": 25000, "copper_ore": 15000, "coal": 20000, "stone": 12000}

# When a farther field is claimed, nearer fields lose up to this fraction of their
# remaining reserve (scaled by how much closer they are) - pushes the frontier out.
EXPANSION_DEPLETE_K = 0.20

# Fraction of a reclaimed field's track materials refunded when it is abandoned.
RECLAIM_REFUND = 0.5

# ---------------------------------------------------------------------------
# Trains
# ---------------------------------------------------------------------------
CARGO_WAGON_CAPACITY = 2000        # items per wagon (single int, no stacks)
DEFAULT_WAGONS = 2                 # per train
BASE_UNLOAD_RATE = 200             # items/sec a train unloads at home (slow to start;
                                   # research raises it via research.unload_mult)
TRAIN_MAX_SPEED = 8.0              # tiles/sec
TRAIN_ACCEL = 4.0                 # tiles/sec^2
ENTITY_LEN = 4                     # loco / wagon length in tiles (small enough that
                                   # trains on the two parallel lanes clear each other)
ENTITY_WIDTH = 1.5                 # drawn car width in tiles
COUPLING = 1                       # tile gap between cars
MAX_TRAIN_LEN = 15                 # 1 loco + 2 wagons + couplings (used for block spacing)

COAL_BURN_SECONDS = 6.67           # run-seconds added per 1 coal
LOCO_FUEL_SLOTS = 3                # max coal a loco holds
LOCO_START_FUEL = 3               # coal a freshly-built loco carries

# Train-vs-train collision avoidance: a train yields to any HIGHER-PRIORITY train
# (loaded/returning beats empty/outbound; id breaks ties) whose car comes within
# COLLISION_DIST of the path just ahead, plus to whoever holds the home junction.
# Handles crossings between different fields' loops and departing into a crash.
TRAIN_COLLISION_DIST = 3.2         # tiles
TRAIN_LOOKAHEAD = 4.0              # tiles ahead the head checks for obstacles

# Home junction interlock: every loop fans out through the origin (0,0), so the
# convergence there is a single interlocked junction. A train reserves it (a
# chain signal at the throat) BEFORE entering and only one train crosses at a
# time; the rest queue just outside instead of stopping in the crossing and
# blocking cross-traffic. Higher-priority (loaded/returning) trains win the grant.
JUNCTION_RADIUS = 8.0              # tiles around origin treated as the home junction
JUNCTION_CLEAR = 1.5              # extra tiles the tail must pass before releasing
JUNCTION_APPROACH = 6.0           # within this of the throat a train requests the grant

# ---------------------------------------------------------------------------
# Rail network
# ---------------------------------------------------------------------------
RAIL_GRID = 2                      # rail nodes snap to even tile coords on straights
LANE_OFFSET = 10                   # gap between the two one-way lanes (tiles); also the
                                   # diameter of the U-turn loops, so trains never turn sharp
CURVE_RADIUS = 6                   # corner-rounding radius (tiles); no sharp corners
SIGNAL_SPACING = 16                # >= MAX_TRAIN_LEN; one block per this many tiles
OCCUPANCY_PENALTY = 1000           # added to route cost for a locked block

# ---------------------------------------------------------------------------
# Starting inventory (bootstraps the whole loop)
# ---------------------------------------------------------------------------
# Enough to stand up all four resource types (iron, copper, coal, stone) as the
# first fields, plus seed materials - this avoids a bootstrap deadlock where a new
# field needs a locomotive but a locomotive needs copper from a field you can't
# yet build. The user explicitly asked to "start with enough materials".
STARTING_INVENTORY = {
    "burner_drill": 16,
    "electric_drill": 0,
    "stone_furnace": 16,
    "coal": 600,
    "assembler": 4,
    "train_stop": 10,
    "rail": 250,
    "rail_signal": 30,
    "chain_signal": 12,
    "locomotive": 4,
    "cargo_wagon": 8,
    "iron_plate": 300,
    "copper_plate": 250,
    "steel_plate": 100,
    "stone": 200,
}

# Home production capacity the base starts with (auto-crafts toward targets below).
HOME_START = {
    "furnaces": 20,        # stone-furnace equivalents at home for smelting ore->plate
    "assemblers": 6,       # assemblers for the crafting chain
}

# The auto-crafter keeps roughly this much of each buildable in stock; the
# director spends the surplus to expand. Tunes how "ready" the base feels.
STOCK_TARGETS = {
    "rail": 250, "rail_signal": 30, "chain_signal": 12,
    "electric_drill": 8, "train_stop": 8, "assembler": 2,
    "stone_furnace": 8, "locomotive": 3, "cargo_wagon": 6,
    "science_pack": 120,    # accumulate research currency from surplus production
    "robot": 3,             # keep robots ready to deploy up to the research cap
}

# ---------------------------------------------------------------------------
# Storage (per-resource, NOT global)
# ---------------------------------------------------------------------------
# Every resource has its OWN finite storage at the base - coal storage is separate
# from iron storage, plates, rails, etc. Caps start TIGHT (the base fills fast and
# overflow can't be held) and grow only by BUILDING more storage, which is
# deliberately expensive, so capacity is a real per-resource constraint and a
# steel sink. An item absent from STORAGE_CAP_START is uncapped (the transient
# crafting intermediates: sticks, cable, gears, circuits, engines).
STORAGE_CAP_START = {
    # raw ore: must hold at least a wagon-load (2000) to unload; still tight so the
    # base backs up within the first few minutes once mining ramps
    "iron_ore": 2500, "copper_ore": 2500, "coal": 2500, "stone": 2500,
    # smelted plates
    "iron_plate": 600, "copper_plate": 500, "steel_plate": 300, "stone_brick": 300,
    # research currency
    "science_pack": 120,
    # buildables
    "rail": 400, "rail_signal": 60, "chain_signal": 30, "train_stop": 30,
    "burner_drill": 30, "electric_drill": 30, "stone_furnace": 30, "assembler": 20,
    "locomotive": 20, "cargo_wagon": 30, "robot": 10,
}
# Capacity ONE storage build adds to a single resource (its own location). Each
# step is well under that resource's starting cap so capacity grows gradually
# (one build is a fraction more room, never a doubling).
STORAGE_CAP_STEP = {
    "iron_ore": 2000, "copper_ore": 2000, "coal": 2000, "stone": 2000,
    "iron_plate": 400, "copper_plate": 300, "steel_plate": 200, "stone_brick": 200,
    "science_pack": 60,
    "rail": 200, "rail_signal": 30, "chain_signal": 15, "train_stop": 15,
    "burner_drill": 15, "electric_drill": 15, "stone_furnace": 15, "assembler": 10,
    "locomotive": 10, "cargo_wagon": 15, "robot": 5,
}
# Materials one storage build costs (for any single resource). Mostly stone (the
# silo material - abundant but a real sink) plus some iron plate; deliberately NOT
# steel, which is the perpetual bottleneck and would make storage unaffordable.
# Steep enough that capacity grows slowly even when something is backing up.
STORAGE_COST = {"stone": 120, "iron_plate": 30}
# A resource at/above this fraction of its cap is "backing up" -> build storage.
STORAGE_RELIEF_FRACTION = 0.9
# The heuristic won't grow any single resource's storage past this multiple of its
# starting cap - a permanently-surplus resource (e.g. coal mined faster than burned)
# is left to overflow rather than getting an ever-growing silo. Keeps growth slow
# and bounded; the LLM director may still choose otherwise.
STORAGE_MAX_MULT = 5.0

# ---------------------------------------------------------------------------
# World generation
# ---------------------------------------------------------------------------
MAP_RADIUS = 160                   # half-size of the square map in tiles
SCOUT_REVEAL_RADIUS = 9            # tiles revealed around the explorer robot
SCOUT_SPEED = 6.0                  # tiles/sec (explorer robot)
TRAIN_REVEAL_RADIUS = 7            # tiles each moving train clears around its cars
                                   # (rails become sightlines: trains chart their route)
PATCH_COUNT = 60                   # ore patches scattered across the map
PATCH_MIN_RING = 30                # barren ring around HQ; nearest patches start here
PATCH_RADIUS = (2, 4)             # patch footprint radius range (tiles)
ORE_WEIGHTS = {"iron_ore": 0.42, "copper_ore": 0.24, "coal": 0.20, "stone": 0.14}

# ---------------------------------------------------------------------------
# Simulation cadence
# ---------------------------------------------------------------------------
DEFAULT_GAME_SPEED = 1.0
GAME_SPEEDS = [0.5, 1.0, 2.0, 4.0, 8.0]
DECISION_INTERVAL = 6.0            # seconds (sim time) between director decisions

# ---------------------------------------------------------------------------
# Robots (the explorer is robot #0; more are built up to the research cap)
# ---------------------------------------------------------------------------
ROBOT_SPEED = 7.0                  # tiles/sec
ROBOT_HP = 140.0
ROBOT_REGEN = 5.0                  # hp/sec self-repair when out of melee
ROBOT_ATTACK = 30.0                # damage per hit to an animal
ROBOT_ATTACK_RANGE = 2.5          # tiles
ROBOT_ATTACK_COOLDOWN = 0.7       # sec between hits
ROBOT_REPAIR_RATE = 14.0          # train HP restored per sec
ROBOT_FUEL_GATHER_RATE = 2.5      # coal/sec gathered as a slow last resort
ROBOT_FUEL_CARRY = 80             # coal a robot can carry per fuel run
ROBOT_HUNT_RADIUS = 70            # only chase animals within this of the robot
ROBOT_RECIPE = {"electronic_circuit": 5, "iron_gear": 8, "steel_plate": 6}

# ---------------------------------------------------------------------------
# Animals (herds wander, can spawn in fog, retaliate only if replaceable)
# ---------------------------------------------------------------------------
ANIMAL_HP = 55.0
ANIMAL_SPEED = 3.2                 # tiles/sec wandering
ANIMAL_CHASE_SPEED = 4.6           # tiles/sec when attacking a robot
ANIMAL_DPS = 5.0                   # damage/sec to a robot in melee
ANIMAL_ATTACK_RANGE = 1.8
ANIMAL_MAX = 40                    # global cap on live animals
HERD_SIZE = (3, 6)
HERD_WANDER_RADIUS = 7             # how far an animal drifts from its herd center
HERD_SPAWN_INTERVAL = 26.0        # sec between herd spawns (sim time)
HERD_DRIFT = 5.0                   # herd-center wander speed scale
ANIMAL_AGGRO_RANGE = 12           # herdmates within this join a retaliation

# ---------------------------------------------------------------------------
# Train health / crushing
# ---------------------------------------------------------------------------
TRAIN_HP = 120.0
TRAIN_CRUSH_DAMAGE = 16.0          # train HP lost per animal crushed
TRAIN_CRUSH_RANGE = 1.7           # tiles from a car center to crush an animal
TRAIN_DAMAGED_THRESHOLD = 0.4      # HP fraction below which a train slows
TRAIN_DAMAGED_SPEED = 0.5          # speed multiplier while heavily damaged
FUEL_CRITICAL = 60                 # home coal below this triggers robot fuel runs

# ---------------------------------------------------------------------------
# Tech tree (1000 levels; effects are COMPUTED from the level, not hand-authored)
# ---------------------------------------------------------------------------
# The director researches one level at a time, spending tech_cost(level) science.
# Every multiplier is a closed-form function of the current level: tiny per-level
# gains that COMPOUND, so the empire starts near 1x and, deep into the hundreds,
# mining/smelting/crafting/storage/construction run orders of magnitude faster.
# Reaching the hundreds takes a long time (many research steps + rising cost), so
# it's a slow burn that snowballs - classic idle-game curve. All capped so the
# simulation stays numerically sane.
import math as _math

BASE_MAX_ROBOTS = 3                # starting robot cap (raised by Robotics tech)
MAX_TECH_LEVEL = 1000


def _compound(level: int, rate: float, cap: float) -> float:
    """(1+rate)^level, clamped to cap. ~1%/level => 2.7x at L100, ~145x at L500."""
    if level <= 0:
        return 1.0
    return min(cap, (1.0 + rate) ** level)


def _approach(level: int, ceiling: float, half: float) -> float:
    """Smoothly rise from 1x toward `ceiling`, reaching the half-way point of the
    gain at `half` levels. Used for speeds that must NOT blow up (trains/robots)."""
    return 1.0 + (ceiling - 1.0) * (1.0 - 0.5 ** (level / half))


# throughput multipliers (these are allowed to get very large; storage caps and
# downstream consumption keep the economy from trivially overflowing)
def mining_mult(level: int) -> float:   return _compound(level, 0.011, 4000.0)
def furnace_mult(level: int) -> float:  return _compound(level, 0.010, 2000.0)
def craft_mult(level: int) -> float:    return _compound(level, 0.010, 2000.0)
def storage_mult(level: int) -> float:  return _compound(level, 0.009, 2000.0)
def unload_mult(level: int) -> float:   return _compound(level, 0.010, 3000.0)
def wagon_mult(level: int) -> float:    return _compound(level, 0.008, 200.0)

# speed multipliers (kept bounded so trains/robots stay controllable on the rails)
def train_speed_mult(level: int) -> float:   return _approach(level, 3.0, 120.0)
def train_accel_mult(level: int) -> float:   return _approach(level, 4.0, 120.0)
def construction_mult(level: int) -> float:  return _approach(level, 6.0, 160.0)

def rail_discount(level: int) -> float:      return max(0.25, 1.0 - 0.0008 * level)
def max_robots(level: int) -> int:           return min(12, BASE_MAX_ROBOTS + level // 70)


def tech_cost(level: int) -> int:
    """Science to research TO `level`. Rises ~1%/level so it tracks (a little
    behind) the compounding science output, making progress accelerate."""
    return int(round(8.0 * (1.01 ** level) + level))


# Flavour: rotating category names so each researched level reads like a real tech.
_TECH_TRACKS = [
    ("Mining Productivity", "+mining throughput"),
    ("Logistics", "+train capacity & unload speed"),
    ("Automation", "+crafting speed"),
    ("Electric Smelting", "+smelting speed"),
    ("Warehousing", "+storage capacity"),
    ("Construction Robotics", "+construction speed & robots"),
    ("Rail Engineering", "-rail cost, +train speed"),
]
# Space-program milestones unlock orbital cargo ships (see Simulation).
SPACE_TECH_LEVEL = 40              # first launch capability
_SPACE_NAMES = ["Orbital Logistics", "Interplanetary Trade", "Deep-Space Freight",
                "Galactic Commerce"]


def tech_for_level(level: int) -> dict | None:
    """Describe the tech researched to reach `level` (1..MAX_TECH_LEVEL)."""
    if level < 1 or level > MAX_TECH_LEVEL:
        return None
    if level == SPACE_TECH_LEVEL:
        name, desc = "Spaceflight", "unlocks orbital cargo ships (trade for science)"
    elif level > SPACE_TECH_LEVEL and level % 80 == 0:
        sp = _SPACE_NAMES[min(len(_SPACE_NAMES) - 1, level // 80 - 1)]
        name, desc = sp, "bigger, more frequent orbital trade"
    else:
        track, desc = _TECH_TRACKS[level % len(_TECH_TRACKS)]
        tier = level // len(_TECH_TRACKS) + 1
        name = f"{track} {tier}"
    return {"name": name, "desc": desc, "cost": {"science_pack": tech_cost(level)}}
