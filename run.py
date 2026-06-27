"""AutoFactorio entry point.

Usage:
    python run.py                 play with the LLM director (Golden Eye gateway)
    python run.py --fallback      heuristic director only (no LLM)
    python run.py --seed 42       fixed world seed
    python run.py --config x.json use a specific config file
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AutoFactorio - autonomous train-logistics game")
    ap.add_argument("--fallback", "--no-llm", dest="fallback", action="store_true",
                    help="use the heuristic director only; never call the LLM")
    ap.add_argument("--seed", type=int, default=None, help="world generation seed")
    ap.add_argument("--config", default="config.json", help="path to a config JSON file")
    args = ap.parse_args(argv)

    # ensure the package is importable when launched as a bare script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from autofactorio.config import Config
    from autofactorio.ui.app import App

    cfg = Config.load(args.config if os.path.exists(args.config) else None)
    if args.seed is not None:
        cfg.seed = args.seed
    if args.fallback:
        cfg.llm.enabled = False

    App(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
