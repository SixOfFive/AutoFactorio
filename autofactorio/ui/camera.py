"""2D camera with pan and cursor-centered mouse-wheel zoom.

World units are *tiles* (floats). `zoom` is pixels-per-tile. Screen origin is the
top-left of the window; the camera centers `(cx, cy)` (a world point) in the view.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Camera:
    cx: float = 0.0          # world point (tiles) shown at screen center
    cy: float = 0.0
    zoom: float = 24.0       # pixels per tile
    screen_w: int = 1600
    screen_h: int = 900
    min_zoom: float = 3.0
    max_zoom: float = 80.0

    # ---- coordinate transforms -------------------------------------------
    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        sx = (wx - self.cx) * self.zoom + self.screen_w * 0.5
        sy = (wy - self.cy) * self.zoom + self.screen_h * 0.5
        return sx, sy

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        wx = (sx - self.screen_w * 0.5) / self.zoom + self.cx
        wy = (sy - self.screen_h * 0.5) / self.zoom + self.cy
        return wx, wy

    # ---- interaction ------------------------------------------------------
    def resize(self, w: int, h: int) -> None:
        self.screen_w, self.screen_h = w, h

    def pan_pixels(self, dx: float, dy: float) -> None:
        """Drag the world by a pixel delta (e.g. right-button drag)."""
        self.cx -= dx / self.zoom
        self.cy -= dy / self.zoom

    def pan_world(self, dx: float, dy: float) -> None:
        """Move the camera by a world-unit delta (e.g. WASD per frame)."""
        self.cx += dx
        self.cy += dy

    def zoom_at(self, screen_x: float, screen_y: float, factor: float) -> None:
        """Zoom by `factor` while keeping the world point under the cursor fixed."""
        before = self.screen_to_world(screen_x, screen_y)
        self.zoom = _clamp(self.zoom * factor, self.min_zoom, self.max_zoom)
        after = self.screen_to_world(screen_x, screen_y)
        # Shift the center so the cursor still points at the same world tile.
        self.cx += before[0] - after[0]
        self.cy += before[1] - after[1]

    def center_on(self, wx: float, wy: float) -> None:
        self.cx, self.cy = wx, wy

    # ---- culling helpers --------------------------------------------------
    def visible_tile_bounds(self, margin: int = 1) -> tuple[int, int, int, int]:
        """Integer tile rect (min_x, min_y, max_x, max_y) covering the viewport.

        `margin` pads the edges so partially-visible tiles still draw.
        """
        x0, y0 = self.screen_to_world(0, 0)
        x1, y1 = self.screen_to_world(self.screen_w, self.screen_h)
        import math
        return (
            math.floor(x0) - margin,
            math.floor(y0) - margin,
            math.ceil(x1) + margin,
            math.ceil(y1) + margin,
        )


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v
