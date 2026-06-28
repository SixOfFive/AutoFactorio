"""AutoFactorio entry point.

Usage:
    python run.py                 resume the autosave if one exists, else a new game
    python run.py --new           start fresh, ignoring any autosave
    python run.py --fallback      heuristic director only (no LLM)
    python run.py --seed 42       fixed world seed (also starts fresh)
    python run.py --config x.json use a specific config file
    python run.py --load file     load a specific save on startup

The game autosaves on exit and auto-resumes it on the next launch. Use the
in-game "New game" button (top-right) to reset the timer/map/resources.
"""

from __future__ import annotations

import argparse
import os
import sys


def choose_startup_load(load, new, seed, autosave_path, exists=os.path.exists):
    """Decide which save (if any) to load at startup.

    Precedence: an explicit --load wins; --new or a fixed --seed starts fresh;
    otherwise resume the autosave when it exists.
    """
    if load and exists(load):
        return load
    if new or seed is not None:
        return None
    if autosave_path and exists(autosave_path):
        return autosave_path
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AutoFactorio - autonomous train-logistics game")
    ap.add_argument("--fallback", "--no-llm", dest="fallback", action="store_true",
                    help="use the heuristic director only; never call the LLM")
    ap.add_argument("--seed", type=int, default=None, help="world generation seed (starts fresh)")
    ap.add_argument("--config", default="config.json", help="path to a config JSON file")
    ap.add_argument("--load", default=None, help="load a specific save file on startup")
    ap.add_argument("--new", action="store_true", help="start a fresh game, ignoring the autosave")
    args = ap.parse_args(argv)

    # ensure the package is importable when launched as a bare script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from autofactorio.config import Config
    from autofactorio.ui.app import App, AUTOSAVE_PATH

    cfg = Config.load(args.config if os.path.exists(args.config) else None)
    if args.seed is not None:
        cfg.seed = args.seed
    if args.fallback:
        cfg.llm.enabled = False

    app = App(cfg)
    load_path = choose_startup_load(args.load, args.new, args.seed, AUTOSAVE_PATH)
    if load_path:
        ok, _ = app.sim.load(load_path)
        if ok:
            app.director.reset()
            app.sim.log(f"Resumed from {os.path.basename(load_path)}.")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
