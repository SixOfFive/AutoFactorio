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
    # fuel refining: coal climbs the ladder into ever-denser fuel (see FUEL_BURN/FUEL_POWER).
    # Each step yields far more energy per unit than the coal it consumed, so refining is
    # strongly worth it (raw coal is power-penalized). Top two tiers are tech-gated.
    "compressed_coal":    {"in": {"coal": 3},                                "out": {"compressed_coal": 1},    "time": 1.0},
    "refined_fuel":       {"in": {"compressed_coal": 3},                     "out": {"refined_fuel": 1},       "time": 2.0},
    "nuclear_fuel":       {"in": {"refined_fuel": 4, "steel_plate": 1},      "out": {"nuclear_fuel": 1},       "time": 4.0},
    "fusion_fuel":        {"in": {"nuclear_fuel": 4, "electronic_circuit": 2}, "out": {"fusion_fuel": 1},      "time": 6.0},
    # buildables
    "rail":          {"in": {"iron_stick": 1, "steel_plate": 1, "stone": 1},                       "out": {"rail": 2},          "time": 0.5},
    "rail_signal":   {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"rail_signal": 1},   "time": 0.5},
    "chain_signal":  {"in": {"electronic_circuit": 1, "iron_plate": 5},                            "out": {"chain_signal": 1},  "time": 0.5},
    "train_stop":    {"in": {"electronic_circuit": 5, "iron_plate": 6, "iron_stick": 6, "steel_plate": 3}, "out": {"train_stop": 1}, "time": 0.5},
    # burner drill is COPPER-FREE (iron only) so expansion never hard-stalls on the
    # copper chain - a cheap fallback miner the base can always craft to keep expanding
    "burner_drill":  {"in": {"iron_plate": 3, "iron_gear": 2},                                     "out": {"burner_drill": 1}, "time": 1.0},
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
    "compressed_coal": "Compressed coal", "refined_fuel": "Fuel",
    "nuclear_fuel": "Nuclear fuel", "fusion_fuel": "Fusion fuel",
}

# ---------------------------------------------------------------------------
# Mining / smelting rates
# ---------------------------------------------------------------------------
DRILL_RATE = {"burner": 2.0, "electric": 5.0}     # ore/sec per drill (arcade-tuned for a
                                                   # fast, snowballing superpower economy)
DEFAULT_FIELD_DRILLS = 4                           # drills auto-placed per new field
DEFAULT_FIELD_FURNACES = 0                         # smelting happens at home, not the field

# Patch default reserves by ore type (finite -> forces expansion).
PATCH_RESERVE = {"iron_ore": 25000, "copper_ore": 15000, "coal": 20000, "stone": 12000}

# When a farther field is claimed, nearer fields lose up to this fraction of their
# remaining reserve (scaled by how much closer they are) - pushes the frontier out.
# Kept gentle: each private loop holds one of the base's limited radial slots, so
# depleting fields too fast would keep churning the whole fleet in and out and leave
# the map looking sparse. A slow bleed keeps ~9-12 trains steadily running while the
# frontier still creeps outward.
EXPANSION_DEPLETE_K = 0.10

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

COAL_BURN_SECONDS = 6.67           # train run-seconds added per 1 coal (base tier)
LOCO_FUEL_SLOTS = 3                # fuel units a loco holds (capacity = slots * burn)
LOCO_START_FUEL = 3               # coal a freshly-built loco carries

# ---------------------------------------------------------------------------
# Fuel & power: ONE refinement ladder powers BOTH trains and buildings
# ---------------------------------------------------------------------------
# Coal is refined up the chain coal -> compressed_coal -> refined_fuel ->
# nuclear_fuel -> fusion_fuel (the top two unlocked by tech). Each tier packs FAR more
# energy per unit - both train run-seconds (FUEL_BURN) and building power (FUEL_POWER) -
# so refined fuel "lasts long and gives much more". RAW COAL is PENALIZED: burnt
# directly it yields only half its notional energy as power, which is the whole point
# of refining. Trains and factories both draw the DENSEST fuel in stock first.
FUEL_TIERS = ["coal", "compressed_coal", "refined_fuel", "nuclear_fuel", "fusion_fuel"]
FUEL_ORDER = ["fusion_fuel", "nuclear_fuel", "refined_fuel", "compressed_coal", "coal"]  # best first
FUEL_BURN = {                      # train run-seconds per unit (big jumps per tier)
    "coal": COAL_BURN_SECONDS, "compressed_coal": 24.0, "refined_fuel": 90.0,
    "nuclear_fuel": 400.0, "fusion_fuel": 2000.0,
}
COAL_POWER_PENALTY = 0.5           # raw coal yields only HALF its energy as building power
FUEL_POWER = {                     # building energy per unit (coal already penalized -50%)
    "coal": 1.0 * COAL_POWER_PENALTY, "compressed_coal": 4.0, "refined_fuel": 16.0,
    "nuclear_fuel": 80.0, "fusion_fuel": 400.0,
}
FUEL_COAL_RESERVE = 200            # keep this much raw coal unrefined (the always-available
                                   # base fuel that bootstraps power when refined runs out)
NUCLEAR_FUEL_TECH = 50             # tech level that unlocks nuclear-fuel refining
FUSION_FUEL_TECH = 120             # ...and fusion-fuel refining

# Buildings draw POWER from fuel to run. If supply can't meet demand they run at reduced
# capacity, and at zero fuel they shut off entirely. Demand scales with how many you've
# built, so a sprawling factory needs a big - ideally refined - fuel supply.
POWER_PER_FURNACE = 0.05           # energy/sec a furnace draws to run
POWER_PER_ASSEMBLER = 0.15         # energy/sec an assembler draws to run


def fuel_efficiency(level: int) -> float:
    """Research 'Fuel Efficiency': every fuel burns longer with tech (capped ~2.5x)."""
    return min(2.5, 1.0 + 0.004 * level)

# Train-vs-train collision avoidance: a train yields to any HIGHER-PRIORITY train
# (loaded/returning beats empty/outbound; id breaks ties) whose car comes within
# COLLISION_DIST of the path just ahead, plus to whoever holds the home junction.
# Handles crossings between different fields' loops and departing into a crash.
TRAIN_COLLISION_DIST = 3.2         # tiles
TRAIN_LOOKAHEAD = 4.0              # tiles ahead the head checks for obstacles

# Merge interlock: block reservation alone doesn't protect a MERGE (two one-way
# tracks joining into one), because both approaching trains can creep within
# collision distance of the join before either has claimed the shared downstream
# block - then the hard guard freezes both symmetrically (a deadlock). To fix this
# a train RESERVES the block just ahead of it while still this many tiles short of
# it (so a converging train sees it taken in time), and a train that can't get the
# next block stops this far BEFORE the block boundary (not right at it), leaving the
# block's owner physical clearance to pass through the join un-grazed. Must exceed
# TRAIN_COLLISION_DIST with margin so the waiting train never trips the winner's
# hard guard.
MERGE_CLEAR = 6.0                  # tiles: reserve-ahead distance AND stop-back gap

# Home junction interlock: every loop converges near the origin, so the whole
# central cluster is one interlocked junction. Only ONE train may move inside it
# at a time (a single mutex); everyone else waits OUTSIDE the cluster for their
# turn. On top of that, EVERY train hard-stops before physically overlapping any
# other car, so trains can never collide even mid-manoeuvre. Higher-priority
# (loaded/returning) trains win the grant; a stuck holder is force-released so the
# cluster can never deadlock.
# The region sits JUST INSIDE the home stations (which are LANE_OFFSET=10 out), so
# parked trains stay outside it and never block the one train crossing the origin.
JUNCTION_RADIUS = 9.0              # tiles around origin treated as the home crossing
JUNCTION_CLEAR = 1.5              # extra tiles the tail must pass before releasing
JUNCTION_APPROACH = 7.0           # within this of the crossing a train requests the grant
JUNCTION_STUCK_SECONDS = 2.0      # force-release the mutex if the holder can't progress
UNJAM_SECONDS = 4.0               # a train held this long by traffic gets to push through
                                  # (one at a time, highest priority) so a congested
                                  # cluster can never PERMANENTLY deadlock

# ---------------------------------------------------------------------------
# Rail network
# ---------------------------------------------------------------------------
HOME_RING = 14                     # (legacy) each old dedicated loop's home turnaround radius
HOME_RING_BAY = 7                  # (legacy) extra ring per duplicate loop

# ---------------------------------------------------------------------------
# Private-loop TRUNK network (one disjoint loop per field, deadlock-free)
# ---------------------------------------------------------------------------
# Hard-won lesson from repeated home-area gridlock: ANY design where multiple loops
# converge near the origin deadlocks, because trains from different loops physically
# pile into the cramped centre and hard-stop each other in a cycle no interlock can
# unwind - and a single shared home balloon can only flow 1-2 trains before its
# turnaround knots up. So the deadlock-free invariant is: EXACTLY ONE TRAIN per trunk.
# A lone train on its own loop can never contend with itself - no matter how many
# fields, sidings, crossings or U-turns that loop has. That single rule is what makes
# the base un-jammable, and everything below just preserves it:
#   * ONE train per trunk, always (the train's route is the concatenation of each
#     member field's out-and-back legs - it visits the fields one after another,
#     returning home between each, so it is only ever on ONE leg at a time); and
#   * every trunk's home balloon sits out on a big HOME RING, and trunks are held far
#     enough apart in bearing (>= TRUNK_MERGE_DEG) that no two DIFFERENT trunks' track
#     ever comes within a train's width of each other - so trains on different trunks
#     never interact either.
# A trunk can now carry SEVERAL fields ("milk-run" corridors): as the frontier extends
# outward, a new patch close in bearing to an existing corridor JOINS it (a new siding
# on the shared spine, same one train) instead of consuming a fresh angular slot. This
# is what un-caps the map - the ~16 angular slots no longer bound the field count, each
# slot chains a line of fields running outward - while the one-train rule keeps every
# corridor provably jam-free. (One over-powered train easily out-hauls several slow
# fields, so chaining is also an efficient match of haul capacity to mining rate.)
TRUNK_MERGE_DEG = 22               # MINIMUM bearing separation to PLACE a NEW trunk: a fresh
                                   # corridor is opened at a patch's bearing only if that is
                                   # >= this angle from EVERY existing trunk (see
                                   # RailNetwork._bearing_clear). Keeps distinct corridors far
                                   # enough apart that their sidings never touch.
TRUNK_JOIN_DEG = 8                 # a patch within THIS angle of an existing (non-full) trunk
                                   # JOINS it as another milk-run field instead of opening a new
                                   # corridor. Kept well under TRUNK_MERGE_DEG/2 so a joined
                                   # field's siding (which reaches sideways toward its patch)
                                   # stays inside the corridor's angular band and can never
                                   # overlap a neighbouring trunk's track. Patches between
                                   # TRUNK_JOIN_DEG and TRUNK_MERGE_DEG of every trunk are simply
                                   # refused (expand elsewhere) - the frontier soon offers others.
TRUNK_MAX_FIELDS = 5               # up to this many fields chained on ONE trunk, served by the
                                   # SAME one train. A ceiling (not a target) so a corridor's
                                   # super-cycle stays short enough that each field is revisited
                                   # before its buffer overflows. Raising it is safe for
                                   # deadlock (still one train) but slows per-field service.
TRUNK_HOME_RING = 45               # radius of a trunk's home balloon-loop (the unload depot).
                                   # BIG on purpose: out here the balloons sit spread around a
                                   # wide ring and their inward bulge still stops well short of
                                   # the origin, so loops never converge on the centre (the old
                                   # r=20 ring bulged into the origin and gridlocked). Must stay
                                   # < PATCH_MIN_RING so every field is outside it (outward loop).
TRUNK_STEM_LEN = 14                # spine segment step length
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
# Generous so the director can immediately claim a FLEET of fields and kickstart the
# snowball (lots of ore in -> lots of materials out -> faster expansion), rather than
# crawling out of a one-field bootstrap. Enough drills/locos/wagons for ~10 fields.
STARTING_INVENTORY = {
    "burner_drill": 44,
    "electric_drill": 0,
    "stone_furnace": 16,
    "coal": 800,
    "assembler": 4,
    "train_stop": 24,
    "rail": 600,
    "rail_signal": 60,
    "chain_signal": 12,
    "locomotive": 12,
    "cargo_wagon": 24,
    "iron_plate": 400,
    "copper_plate": 400,
    "steel_plate": 150,
    "stone": 300,
}

# Home production capacity the base starts with (auto-crafts toward targets below).
HOME_START = {
    "furnaces": 20,        # stone-furnace equivalents at home for smelting ore->plate
    "assemblers": 6,       # assemblers for the crafting chain
}

# The auto-crafter keeps roughly this much of each buildable in stock; the director
# spends the surplus to expand. Targets are GENEROUS so the base always has a deep
# bench of factories/drills/rolling-stock ready to deploy in BULK - the director is
# meant to be an industrial superpower that expands fast and furious, not trickle out
# one building at a time. (These are ceilings; actual stock ramps with throughput, so
# the curve still starts slow and snowballs as more factories come online.)
STOCK_TARGETS = {
    "rail": 600, "rail_signal": 60, "chain_signal": 16,
    "burner_drill": 16, "electric_drill": 24, "train_stop": 16, "assembler": 16,
    "stone_furnace": 30, "locomotive": 8, "cargo_wagon": 16,
    "science_pack": 120,    # accumulate research currency from surplus production
    "robot": 3,             # keep robots ready to deploy up to the research cap
    # refine coal up the fuel ladder for power + train range (top tiers tech-gated):
    "compressed_coal": 250, "refined_fuel": 150, "nuclear_fuel": 80, "fusion_fuel": 40,
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
    # refined fuels (denser than coal, so smaller caps go a long way)
    "compressed_coal": 400, "refined_fuel": 200, "nuclear_fuel": 100, "fusion_fuel": 60,
    # research currency
    "science_pack": 120,
    # buildables (generous caps so the deep deployable bench above can actually be held)
    "rail": 800, "rail_signal": 100, "chain_signal": 40, "train_stop": 40,
    "burner_drill": 30, "electric_drill": 50, "stone_furnace": 60, "assembler": 40,
    "locomotive": 30, "cargo_wagon": 50, "robot": 10,
}
# Capacity ONE storage build adds to a single resource (its own location). Each
# step is well under that resource's starting cap so capacity grows gradually
# (one build is a fraction more room, never a doubling).
STORAGE_CAP_STEP = {
    "iron_ore": 2000, "copper_ore": 2000, "coal": 2000, "stone": 2000,
    "iron_plate": 400, "copper_plate": 300, "steel_plate": 200, "stone_brick": 200,
    "compressed_coal": 250, "refined_fuel": 150, "nuclear_fuel": 80, "fusion_fuel": 40,
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
# The world is ENDLESS: it is not a fixed square. It starts as a MAP_RADIUS-sized grid
# and GROWS outward (the fog canvas is re-centred + enlarged) whenever exploration nears
# the current edge, and ore patches are generated procedurally per CELL on demand, so
# there is always more frontier to explore and more ore to claim - the game never "ends".
MAP_RADIUS = 160                   # INITIAL grid half-size (tiles); the world grows past this
WORLD_GROW_STEP = 128              # grow the fog canvas by this many tiles at a time
WORLD_GROW_MARGIN = 24             # grow once exploration comes within this of the edge
SCOUT_REVEAL_RADIUS = 10           # tiles revealed around the explorer robot
SCOUT_SPEED = 6.0                  # tiles/sec (explorer robot)
TRAIN_REVEAL_RADIUS = 7            # tiles each moving train clears around its cars
                                   # (rails become sightlines: trains chart their route)
PATCH_CELL = 40                    # the plane is diced into CELL x CELL cells; each cell gets a
                                   # patch (with PATCH_CELL_PROB) generated deterministically from
                                   # (seed, cell) the first time the cell is materialised, so the
                                   # ore field is endless yet reproducible + save-safe.
PATCH_CELL_PROB = 0.70             # chance a cell contains an ore patch
PATCH_RICH_SCALE = 600.0           # patches get richer with distance: reserve *= 1 + dist/this,
                                   # so the ever-receding frontier is always worth expanding to.
PATCH_COUNT = 60                   # (legacy; unused - patch count is now emergent from cells)
PATCH_MIN_RING = 54                # barren ring around HQ; nearest patches start here. Must sit
                                   # OUTSIDE TRUNK_HOME_RING (the depot ring) so every field lies
                                   # beyond its trunk's home balloon and the loop runs outward.
PATCH_RADIUS = (2, 4)             # patch footprint radius range (tiles)
ORE_WEIGHTS = {"iron_ore": 0.42, "copper_ore": 0.24, "coal": 0.20, "stone": 0.14}

# ---------------------------------------------------------------------------
# Simulation cadence
# ---------------------------------------------------------------------------
DEFAULT_GAME_SPEED = 1.0
GAME_SPEEDS = [0.5, 1.0, 2.0, 4.0, 8.0]
DECISION_INTERVAL = 4.0            # seconds (sim time) between director decisions - snappy
                                   # so the empire expands fast and furious

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

# Orbital cargo ships: once Spaceflight is researched the base periodically launches
# a rocket that consumes a payload of goods and trades it for SCIENCE (which feeds
# back into the tech tree). Tech makes launches more frequent and more lucrative.
SHIP_COST = {"steel_plate": 20, "electronic_circuit": 10, "coal": 40}
SHIP_LAUNCH_INTERVAL = 22.0        # base seconds between launches (shrinks with tech)
SHIP_REWARD_SCIENCE = 25           # base science traded back per launch (scales w/ level)
SHIP_CLIMB_SPEED = 16.0            # tiles/sec the rocket ascends on screen
SHIP_ASCEND_TILES = 64.0           # distance up before it reaches orbit and delivers


def ship_reward(level: int) -> int:
    return int(SHIP_REWARD_SCIENCE * (1.0 + level / 20.0))


def ship_interval(level: int) -> float:
    return SHIP_LAUNCH_INTERVAL / (1.0 + level / 200.0)


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
