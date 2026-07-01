# AutoFactorio architecture

A top-down, self-running train-logistics game. Mining fields auto-mine ore →
one-way trains haul it home → the home factory consumes ore to build more track,
drills, and trains → an LLM director spends that stock to expand the network →
a scout reveals fog of war so there's always somewhere new to grow.

The guiding split (borrowed from the SimCity_LLM project): **the LLM owns
strategy, deterministic systems own mechanics.** The director only decides *what*
to build; track routing, collision avoidance, smelting, and crafting are all
deterministic and always correct.

## Layers

```
run.py ──► ui/app.py ──► engine/simulation.py ──► engine/{world,rail,trains,mining,economy,scout}
                │                  ▲
                └──► ai/director.py ┘   (report → LLM/heuristic → validate → apply)
```

### engine/ — the authoritative simulation (no pygame, fully headless-testable)
- **world.py** — an **endless** procedurally-generated world. The `explored` fog grid
  (numpy) GROWS (re-centred on HQ + enlarged) whenever exploration nears the current
  edge, and ore patches are generated **deterministically per CELL** the first time a
  cell is materialised (from a `(seed, cell)` RNG), so the ore field is infinite yet
  reproducible + save-safe. Patches get **richer with distance** (`PATCH_RICH_SCALE`), so
  the receding frontier is always worth chasing — the game never runs out or "ends".
  Guaranteed starter iron/copper/coal/stone patches near HQ bootstrap the loop.
- **scout** (the explorer robot in **robots.py**) drives an outward Archimedean spiral
  that expands FOREVER (the world is endless), overlapping arms to fill coverage; moving
  trains also reveal fog along their corridors, so new patches keep surfacing outward.
- **rail.py** — directed graph: nodes on the 2-tile lattice, one-way edges with
  polylines, **one block per edge with a mutex `occupant`**, signals at block
  boundaries, stations. `build_link()` lays **two parallel one-way lanes**
  (out + back) between home and a field — the autopilot's connectivity primitive.
- **trains.py** — composition (loco + wagons), movement along a leg's concatenated
  polyline, **block acquire/release as the body moves** (this is the collision
  guarantee), fuel, cargo, and a looping schedule of legs with wait conditions.
- **mining.py** — a field's drills fill a buffer from its patch at a flat rate.
- **economy.py** — home inventory; furnaces smelt ore→plates; assemblers run a
  recursive auto-crafter toward stock targets. Production work is **banked across
  ticks** (a 60fps frame buys < 1 recipe-time of work) and **round-robined** so
  expensive rolling stock isn't starved by hungry early targets.
- **simulation.py** — owns everything, `tick(dt)`, services parked trains
  (load/unload/refuel + wait evaluation), and exposes the build actions
  (`build_field`, `add_train`, `build_furnace`, `build_assembler`, `expand_drills`)
  that are the deterministic autopilot.

### ai/ — the director
- **report.py** — compact, flat JSON snapshot (inventory, fields, nearest
  claimable patches with affordability, flags like `LOW_COAL`).
- **schema.py** — validates the director's `{reasoning, actions}` into clean,
  typed actions; drops anything malformed so a chatty model can't crash apply.
- **apply.py** — maps actions to Simulation methods (main thread only).
- **fallback.py** — heuristic director (same output shape): secure iron/copper/
  coal/stone first, then expand to the nearest affordable patch, relieve full
  fields with trains, scale production.
- **client.py** — stdlib OpenAI-compatible client (Golden Eye gateway), forced
  JSON, `/no_think`, defensive JSON extraction.
- **director.py** — runs the slow LLM call on a daemon thread; **all sim reads/
  writes stay on the main thread**. On gateway error it logs and falls back to
  the heuristic for that turn, retrying the LLM later.

### ui/ — presentation (pygame-ce)
- **camera.py** — two strict-inverse transforms; cursor-anchored wheel zoom.
- **assets.py** — loads procedural sprites; caches scaled + 5°-bucketed rotations.
- **renderer.py** — viewport-culled draw of terrain, ore, the home **terminal** (a paved
  concourse + central plaza with an island platform at every corridor's berth, so the
  radiating one-train corridors read as ONE station whose double-track lines lead away),
  one-way rails (with direction arrows + occupancy-colored signals), stations, fields,
  home factory, trains, scout, and the numpy fog overlay (built per-frame from the slice).
- **hud.py / console.py** — top stats bar and bottom director/scout comms log.
- **app.py** — window, input, and the update/draw loop.

## Collision-free shared-track network
Real Factorio uses rail + chain signals to carve track into mutually-exclusive
blocks (one train per block). AutoFactorio keeps that invariant and drops the
geometry: track is a **directed** graph built as two parallel one-way lanes, each
edge is its own block with a lock, and a train acquires the blocks under its body
and releases them behind it. Head-on collisions are structurally impossible
(directed edges) and same-lane rear-end collisions are prevented by the block
mutex (blocks are sized >= a train length).

**Every corridor is run by exactly ONE train** (`engine/rail.py` `Trunk`): a home
balloon-loop + unload depot out on a big **home ring**, a straight radial spine, and a
short **siding** (out-lane → patch U-turn → in-lane) for each field it serves. The
deadlock-free invariant, reached the hard way, is simply **one train per corridor** - a
lone train can never contend with itself no matter how many fields, sidings or U-turns
its loop has (every design that let *different* loops converge near the origin, or put
2+ trains through a single balloon, gridlocked: trains hard-stop nose-to-tail in a cycle
no interlock can unwind).

A corridor is a **milk-run**: its one train's route is the concatenation of each member
field's out-and-back legs (`Simulation._trunk_legs`), so it visits the fields one after
another - out to a field, load, U-turn, home to unload, out to the next - and is only
ever on ONE leg at a time. This lifts the old one-field-per-slot cap: as the frontier
extends, a new patch close in bearing to an existing corridor **joins** it (another
siding on the shared spine, same train) instead of consuming a fresh angular slot, so
the map fills densely with corridors chaining several fields outward.

Two guarantees keep it jam-free:
1. **One train per corridor** (`add_train` disabled; a corridor's single train is
   dispatched/rebuilt by `_ensure_trunk_train` / `_rebuild_trunk_train`).
2. **Corridors never converge.** A new corridor is *radial* and is only opened if its
   bearing is `>= TRUNK_MERGE_DEG` from every existing corridor (`_bearing_clear`); a
   field only *joins* an existing corridor if within `TRUNK_JOIN_DEG` (kept well under
   `TRUNK_MERGE_DEG/2` so a joined field's siding stays inside the corridor's angular
   band and can never reach a neighbour). Patches stuck between those angles are refused
   (`build_field` returns "no free rail corridor").

Because two *different* corridors never share a block or a crossing - and a corridor's
lone train never contends with itself - the block mutex + home-throat interlock
(`Simulation._arbitrate_junction`) have nothing to resolve and the base can't jam. When a
field depletes it is dropped from its corridor's route the next time the train is home,
and its siding + drills reclaimed (`_rebuild_trunk_train`); when the *last* field on a
corridor depletes the train is stored and the whole corridor torn down, freeing the
angular slot at once. Fields lie beyond the home ring (`PATCH_MIN_RING > TRUNK_HOME_RING`),
so every loop runs cleanly outward. `MERGE_CLEAR` reserve-ahead block locking keeps a
train that must wait for a block stopping with real clearance rather than nosing up to it.

## Testing
Headless smoke tests (no window, run with the venv python):
- `tests/smoke_engine.py` — the mine→haul→smelt→craft loop.
- `tests/smoke_director.py` — autonomous multi-field self-expansion.
- `tests/smoke_ui.py` — the full render loop across zoom levels (SDL dummy driver).
- `tests/screenshot.py` — render N seconds and save a PNG.
