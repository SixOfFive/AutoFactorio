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
    "steel_plate":  {"in": {"iron_plate": 5}, "out": {"steel_plate": 1},  "time": 16.0},
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
    "engine_unit":        {"in": {"iron_gear": 1, "steel_plate": 1, "iron_plate": 2}, "out": {"engine_unit": 1}, "time": 10.0},
    # buildables
    "rail":          {"in": {"iron_stick": 1, "steel_plate": 1, "stone": 1},                       "out": {"rail": 2},          "time": 0.5},
    "rail_signal":   {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"rail_signal": 1},   "time": 0.5},
    "chain_signal":  {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"chain_signal": 1},  "time": 0.5},
    "train_stop":    {"in": {"electronic_circuit": 5, "iron_plate": 6, "iron_stick": 6, "steel_plate": 3}, "out": {"train_stop": 1}, "time": 0.5},
    "electric_drill":{"in": {"electronic_circuit": 3, "iron_gear": 5, "iron_plate": 10},           "out": {"electric_drill": 1},"time": 2.0},
    "stone_furnace": {"in": {"stone": 5},                                                          "out": {"stone_furnace": 1}, "time": 0.5},
    "assembler":     {"in": {"electronic_circuit": 3, "iron_gear": 5, "iron_plate": 9},            "out": {"assembler": 1},     "time": 0.5},
    "locomotive":    {"in": {"electronic_circuit": 10, "engine_unit": 20, "steel_plate": 30},      "out": {"locomotive": 1},    "time": 4.0},
    "cargo_wagon":   {"in": {"iron_gear": 10, "iron_plate": 20, "steel_plate": 20},                "out": {"cargo_wagon": 1},   "time": 1.0},
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
    "cargo_wagon": "Cargo wagon",
}

# ---------------------------------------------------------------------------
# Mining / smelting rates
# ---------------------------------------------------------------------------
DRILL_RATE = {"burner": 0.25, "electric": 0.5}    # ore/sec per drill
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
ENTITY_LEN = 6                     # loco / wagon length in tiles
COUPLING = 1                       # tile gap between cars
MAX_TRAIN_LEN = 20                 # 1 loco + 2 wagons + couplings (used for block spacing)

COAL_BURN_SECONDS = 6.67           # run-seconds added per 1 coal
LOCO_FUEL_SLOTS = 3                # max coal a loco holds
LOCO_START_FUEL = 3               # coal a freshly-built loco carries

# ---------------------------------------------------------------------------
# Rail network
# ---------------------------------------------------------------------------
RAIL_GRID = 2                      # rail nodes only on even tile coords
LANE_OFFSET = 2                    # perpendicular gap between the two one-way lanes (tiles)
SIGNAL_SPACING = 20                # >= MAX_TRAIN_LEN; one block per this many tiles
OCCUPANCY_PENALTY = 1000           # added to route cost for a locked block

# ---------------------------------------------------------------------------
# Starting inventory (bootstraps the whole loop)
# ---------------------------------------------------------------------------
STARTING_INVENTORY = {
    "burner_drill": 8,
    "electric_drill": 0,
    "stone_furnace": 16,
    "coal": 500,
    "assembler": 4,
    "train_stop": 6,
    "rail": 120,
    "rail_signal": 20,
    "chain_signal": 8,
    "locomotive": 1,
    "cargo_wagon": 2,
    "iron_plate": 200,
    "copper_plate": 100,
    "steel_plate": 50,
    "stone": 100,
}

# Home production capacity the base starts with (auto-crafts toward targets below).
HOME_START = {
    "furnaces": 16,        # stone-furnace equivalents at home for smelting ore->plate
    "assemblers": 4,       # assemblers for the crafting chain
}

# The auto-crafter keeps roughly this much of each buildable in stock; the
# director spends the surplus to expand. Tunes how "ready" the base feels.
STOCK_TARGETS = {
    "rail": 200, "rail_signal": 30, "chain_signal": 12,
    "electric_drill": 8, "train_stop": 6, "assembler": 2,
    "stone_furnace": 8, "locomotive": 2, "cargo_wagon": 4,
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
