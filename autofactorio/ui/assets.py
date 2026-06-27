"""Sprite asset manager: ensures the procedural sprites exist, loads them, and
caches scaled / rotated variants so we never transform per-blit per-frame.
"""

from __future__ import annotations

import os

import pygame

# import the generator (sits in the repo-root assets/ dir)
import importlib.util

_ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")
_SPRITE_DIR = os.path.join(_ASSET_DIR, "sprites")


def _load_generator():
    path = os.path.join(_ASSET_DIR, "generate_assets.py")
    spec = importlib.util.spec_from_file_location("generate_assets", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Assets:
    def __init__(self) -> None:
        gen = _load_generator()
        gen.ensure_assets(_SPRITE_DIR)             # create any missing PNGs
        self.base: dict[str, pygame.Surface] = {}
        for name in gen.SPRITE_NAMES:
            path = os.path.join(_SPRITE_DIR, f"{name}.png")
            self.base[name] = pygame.image.load(path).convert_alpha()
        self._scaled: dict[tuple[str, int], pygame.Surface] = {}
        self._rotated: dict[tuple[str, int, int], pygame.Surface] = {}

    def scaled(self, name: str, px: int) -> pygame.Surface:
        px = max(1, int(px))
        key = (name, px)
        s = self._scaled.get(key)
        if s is None:
            s = pygame.transform.smoothscale(self.base[name], (px, px))
            if len(self._scaled) > 4000:
                self._scaled.clear()
            self._scaled[key] = s
        return s

    def rotated(self, name: str, px: int, angle_deg: float) -> pygame.Surface:
        px = max(1, int(px))
        bucket = int(round(angle_deg / 5.0)) % 72        # 5-degree buckets
        key = (name, px, bucket)
        s = self._rotated.get(key)
        if s is None:
            base = self.scaled(name, px)
            s = pygame.transform.rotate(base, bucket * 5.0)
            if len(self._rotated) > 6000:
                self._rotated.clear()
            self._rotated[key] = s
        return s
