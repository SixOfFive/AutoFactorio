"""Headless UI smoke test: drive the full app (renderer + HUD + console) for a
few hundred frames under the SDL dummy video driver, with the heuristic director
so fields/trains get built and every draw path is exercised. Catches runtime
errors in rendering without needing a real window.

Run:  .venv\\Scripts\\python tests\\smoke_ui.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from autofactorio.config import Config  # noqa: E402
from autofactorio.ui.app import App  # noqa: E402


def main() -> int:
    cfg = Config()
    cfg.llm.enabled = False
    cfg.display.width, cfg.display.height = 1280, 720
    app = App(cfg)

    zooms = [20.0, 4.0, 60.0, 12.0]
    for frame in range(600):           # ~10s sim at 60fps
        pygame.event.pump()
        app.cam.zoom = zooms[(frame // 150) % len(zooms)]   # exercise zoom buckets
        app.sim.tick(1 / 60)
        app.director.update()
        app._draw()
        pygame.display.flip()

    s = app.sim.stats()
    print("ui smoke stats:", s)
    print(f"director decisions: {app.director.decisions}, source={app.director.source}")
    assert s["fields"] >= 1, "no field built during UI run"
    assert s["trains"] >= 1, "no train to render"
    pygame.quit()
    print("\nUI SMOKE OK: full render loop ran clean across zoom levels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
