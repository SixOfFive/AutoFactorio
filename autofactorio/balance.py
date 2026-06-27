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
    "cargo_wagon": "Cargo wagon", "science_pack": "Science",
}

# ---------------------------------------------------------------------------
# Mining / smelting rates
# ---------------------------------------------------------------------------
DRILL_RATE = {"burner": 0.8, "electric": 2.0}     # ore/sec per drill (arcade-tuned for pace)
DEFAULT_FIELD_DRILLS = 4                           # drills auto-placed per new field
DEFAULT_FIELD_FURNACES = 0                         # smelting happens at home, not the field

# Patch default reserves by ore type (finite -> forces expansion).
PATCH_RESERVE = {"iron_ore": 25000, "copper_ore": 15000, "coal": 20000, "stone": 12000}

# ---------------------------------------------------------------------------
# Trains
# ---------------------------------------------------------------------------
CARGO_WAGON_CAPACITY = 2000        # items per wagon (single int, no stacks)
DEFAULT_WAGONS = 2                 # per train
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

# ---------------------------------------------------------------------------
# Rail network
# ---------------------------------------------------------------------------
RAIL_GRID = 2                      # rail nodes only on even tile coords
LANE_OFFSET = 4                    # perpendicular gap between the two one-way lanes (tiles)
                                   # wide enough that trains on opposite lanes pass clear
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
}

# ---------------------------------------------------------------------------
# World generation
# ---------------------------------------------------------------------------
MAP_RADIUS = 160                   # half-size of the square map in tiles
SCOUT_REVEAL_RADIUS = 9            # tiles revealed around the scout
SCOUT_SPEED = 6.0                  # tiles/sec
PATCH_COUNT = 60                   # ore patches scattered across the map
PATCH_MIN_RING = 18                # nearest patch distance from HQ (tiles)
PATCH_RADIUS = (2, 4)             # patch footprint radius range (tiles)
ORE_WEIGHTS = {"iron_ore": 0.42, "copper_ore": 0.24, "coal": 0.20, "stone": 0.14}

# ---------------------------------------------------------------------------
# Simulation cadence
# ---------------------------------------------------------------------------
DEFAULT_GAME_SPEED = 1.0
GAME_SPEEDS = [0.5, 1.0, 2.0, 4.0, 8.0]
DECISION_INTERVAL = 6.0            # seconds (sim time) between director decisions

# ---------------------------------------------------------------------------
# Tech tree (researched in order; each spends its cost and applies its effect)
# ---------------------------------------------------------------------------
BASE_MAX_ROBOTS = 1                # explorer robots before Robotics research

TECHS = [
    {"name": "Mining Productivity 1", "cost": {"science_pack": 10},
     "effect": {"drill_mult": 1.5}, "desc": "+50% drill output"},
    {"name": "Train Braking 1", "cost": {"science_pack": 14},
     "effect": {"train_speed": 1.25, "train_accel": 1.3}, "desc": "faster trains"},
    {"name": "Cargo Capacity 1", "cost": {"science_pack": 18},
     "effect": {"wagon_capacity": 1.5}, "desc": "+50% wagon capacity"},
    {"name": "Electric Smelting", "cost": {"science_pack": 24},
     "effect": {"furnace_mult": 1.5}, "desc": "+50% smelting speed"},
    {"name": "Rail Engineering", "cost": {"science_pack": 30},
     "effect": {"rail_discount": 0.8}, "desc": "-20% rail cost per link"},
    {"name": "Mining Productivity 2", "cost": {"science_pack": 40},
     "effect": {"drill_mult": 1.5}, "desc": "+50% drill output"},
    {"name": "Robotics 1", "cost": {"science_pack": 50},
     "effect": {"max_robots": 1}, "desc": "+1 explorer robot"},
    {"name": "Cargo Capacity 2", "cost": {"science_pack": 64},
     "effect": {"wagon_capacity": 1.5}, "desc": "+50% wagon capacity"},
    {"name": "Train Braking 2", "cost": {"science_pack": 80},
     "effect": {"train_speed": 1.25, "train_accel": 1.3}, "desc": "faster trains"},
    {"name": "Robotics 2", "cost": {"science_pack": 100},
     "effect": {"max_robots": 1}, "desc": "+1 explorer robot (max 3)"},
]
