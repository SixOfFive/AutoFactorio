"""Render the game headlessly for a while and save a screenshot PNG.

Run:  .venv\\Scripts\\python tests\\screenshot.py [seconds] [out.png]
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
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "autofactorio_screenshot.png")

    cfg = Config()
    cfg.llm.enabled = False
    cfg.display.width, cfg.display.height = 1600, 900
    app = App(cfg)
    app.cam.zoom = 9.0
    app.cam.center_on(0, 0)

    steps = int(seconds * 60)
    for _ in range(steps):
        pygame.event.pump()
        app.sim.tick(1 / 60)
        app.director.update()
    app._draw()
    pygame.display.flip()

    pygame.image.save(app.screen, out)
    print(f"saved {os.path.abspath(out)}  |  stats={app.sim.stats()}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
