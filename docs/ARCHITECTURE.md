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
- **world.py** — tile map, `explored` fog grid (numpy), finite ore patches with
  reserves. Guaranteed starter iron+coal patches near HQ so the loop bootstraps.
- **scout.py** — drives an outward Archimedean spiral, revealing a radius of fog
  each step and discovering patches.
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
- **renderer.py** — viewport-culled draw of terrain, ore, one-way rails (with
  direction arrows + occupancy-colored signals), stations, fields, home factory,
  trains, scout, and the numpy fog overlay (built per-frame from the visible slice).
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

Fields are NOT each given a private loop. They are grouped into angular **sectors**
(`engine/rail.py` `Trunk`): each sector has ONE shared double-track **main line** -
a home balloon-loop with a single unload stop, then a straight radial spine running
outward. A field attaches to its sector's trunk via a short **siding** at its own
radius (`attach_field`), so trains for different fields **follow each other along the
common spine** (intermingling, multi-destination shared track) and only the short
sidings are private. Same-direction fields therefore share a corridor instead of
piling separate loops onto the home area (which used to gridlock).

The one spot too small for two trains is each trunk's home **throat** (the balloon
turnaround), so it's an interlock: at most one train traverses a throat at a time
(`Simulation._arbitrate_junction`), granted to the train nearest to entering (front
of queue, avoiding priority inversion) and held until its whole train clears. The
unload stop sits just OUTSIDE the throat, so returning trains always reach it without
contending - only departing trains queue for the turnaround. A trunk caps how many
fields share its throat (`TRUNK_MAX_FIELDS`); an extra in-direction field starts a new
trunk. A global anti-deadlock watchdog lets the single most-stuck train push through
if the whole network ever freezes, so it can never permanently lock up.

## Testing
Headless smoke tests (no window, run with the venv python):
- `tests/smoke_engine.py` — the mine→haul→smelt→craft loop.
- `tests/smoke_director.py` — autonomous multi-field self-expansion.
- `tests/smoke_ui.py` — the full render loop across zoom levels (SDL dummy driver).
- `tests/screenshot.py` — render N seconds and save a PNG.
