"""Procedural CC0 sprite generation for AutoFactorio.

Every image in the game is drawn from scratch here with pygame primitives, so the
art is public-domain by construction (no Factorio or third-party assets) and
deterministic: the same seed always produces byte-identical PNGs.

Two entry points:
  * ensure_assets(sprite_dir) - generate only the files that are missing. Safe to
    call from inside the running game (does NOT touch global pygame init/quit, the
    bug that crashed SimCity_LLM's first run).
  * python assets/generate_assets.py [--force]  - (re)generate everything.

Sprites are authored at TILE=64 px and scaled by the renderer at draw time.
"""

from __future__ import annotations

import math
import os
import random
import sys

import pygame

TILE = 64

# Canonical sprite list. Keys are the filenames (without .png) the renderer asks for.
SPRITE_NAMES = [
    "grass",
    "ore_iron", "ore_copper", "ore_coal", "ore_stone", "ore_uranium",
    "mining_drill",
    "smelter",
    "assembler",
    "boiler", "nuclear_plant",
    "hq",
    "train_stop",
    "locomotive", "locomotive_2", "locomotive_3", "locomotive_4",
    "wagon", "wagon_2", "wagon_3", "wagon_4",
    "rocket",
    "scout",
    "animal",
    "tree", "rock",
]

# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------
PAL = {
    "grass_a": (78, 122, 64),
    "grass_b": (88, 134, 72),
    "grass_c": (66, 108, 56),
    "iron": (122, 138, 158), "iron_d": (84, 98, 116),
    "copper": (200, 118, 64), "copper_d": (150, 80, 40),
    "coal": (44, 44, 50), "coal_d": (24, 24, 28),
    "stone": (176, 162, 130), "stone_d": (132, 120, 92),
    "uranium": (132, 224, 104), "uranium_d": (74, 150, 68),   # glowing green reactor ore
    "glow": (150, 240, 120),
    "metal": (96, 100, 108), "metal_d": (60, 63, 70), "metal_l": (140, 144, 152),
    "hazard": (224, 188, 40),
    "ember": (255, 150, 40),
    "ember_hot": (255, 214, 120),
    "brick": (150, 86, 70), "brick_d": (110, 60, 48),
    "steel": (120, 128, 140), "steel_l": (170, 178, 190),
    "loco_red": (188, 52, 48), "loco_red_d": (140, 34, 32),
    "loco_blue": (52, 96, 188), "loco_blue_d": (34, 64, 140),
    "loco_green": (60, 150, 72), "loco_green_d": (40, 110, 52),
    "loco_dark": (74, 78, 90), "loco_dark_d": (46, 50, 60),
    "wagon_brown": (130, 96, 60), "wagon_brown_d": (96, 70, 44),
    "wagon_steel": (122, 130, 142), "wagon_steel_d": (90, 96, 108),
    "wagon_olive": (122, 122, 72), "wagon_olive_d": (90, 90, 50),
    "wagon_gray": (110, 112, 120), "wagon_gray_d": (80, 82, 90),
    "scout_yellow": (236, 200, 72), "scout_yellow_d": (190, 158, 48),
    "glass": (150, 210, 235),
    "outline": (22, 24, 28),
    "wood": (110, 78, 46), "wood_d": (82, 58, 34),
    "leaf": (54, 104, 56), "leaf_d": (40, 82, 44),
}


def _rng(name: str) -> random.Random:
    """Deterministic per-sprite RNG so regeneration is byte-identical."""
    return random.Random(f"autofactorio:{name}")


def _new() -> pygame.Surface:
    return pygame.Surface((TILE, TILE), pygame.SRCALPHA)


def _outline_circle(surf, color, center, radius, width=0):
    pygame.draw.circle(surf, color, center, radius, width)


def _chunks(surf, name, base, dark, count, rmin, rmax):
    """Scatter shaded ore chunks across a transparent tile."""
    r = _rng(name)
    for _ in range(count):
        cx = r.randint(8, TILE - 8)
        cy = r.randint(8, TILE - 8)
        rad = r.randint(rmin, rmax)
        pygame.draw.circle(surf, PAL["outline"], (cx, cy), rad + 1)
        pygame.draw.circle(surf, dark, (cx, cy), rad)
        pygame.draw.circle(surf, base, (cx - rad // 3, cy - rad // 3), max(2, rad - 3))
        # tiny specular dot
        pygame.draw.circle(surf, _lighten(base, 40), (cx - rad // 2, cy - rad // 2), max(1, rad // 4))


def _lighten(c, amt):
    return tuple(min(255, v + amt) for v in c[:3])


def _darken(c, amt):
    return tuple(max(0, v - amt) for v in c[:3])


# ---------------------------------------------------------------------------
# individual sprites
# ---------------------------------------------------------------------------
def draw_grass(name) -> pygame.Surface:
    s = _new()
    r = _rng(name)
    s.fill(PAL["grass_a"])
    for _ in range(140):
        x, y = r.randint(0, TILE - 1), r.randint(0, TILE - 1)
        col = r.choice([PAL["grass_b"], PAL["grass_c"], PAL["grass_b"]])
        s.set_at((x, y), col)
    # a few blades
    for _ in range(10):
        x = r.randint(4, TILE - 4)
        y = r.randint(8, TILE - 4)
        pygame.draw.line(s, PAL["grass_c"], (x, y), (x + r.randint(-2, 2), y - r.randint(3, 6)))
    return s


def _ore(name, base, dark) -> pygame.Surface:
    s = _new()
    # faint ground so the patch reads even over fog edges
    ground = _darken(base, 70) + (90,)
    pygame.draw.rect(s, ground, (0, 0, TILE, TILE))
    _chunks(s, name, base, dark, count=14, rmin=5, rmax=10)
    return s


def draw_mining_drill(name) -> pygame.Surface:
    s = _new()
    # body
    body = pygame.Rect(8, 8, TILE - 16, TILE - 16)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=6)
    pygame.draw.rect(s, PAL["metal"], body, border_radius=6)
    pygame.draw.rect(s, PAL["metal_l"], (body.x, body.y, body.w, 8), border_radius=6)
    # hazard stripes around the rim
    for i in range(-TILE, TILE, 10):
        pygame.draw.line(s, PAL["hazard"], (body.x + i, body.bottom),
                         (body.x + i + 8, body.bottom - 8), 3)
    # drill head (central cone)
    cx, cy = TILE // 2, TILE // 2
    pygame.draw.polygon(s, PAL["steel_l"], [(cx, cy - 12), (cx - 10, cy + 10), (cx + 10, cy + 10)])
    pygame.draw.polygon(s, PAL["outline"], [(cx, cy - 12), (cx - 10, cy + 10), (cx + 10, cy + 10)], 2)
    pygame.draw.line(s, PAL["metal_d"], (cx, cy - 8), (cx, cy + 8), 2)
    return s


def draw_smelter(name) -> pygame.Surface:
    s = _new()
    body = pygame.Rect(10, 12, TILE - 20, TILE - 20)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=5)
    pygame.draw.rect(s, PAL["brick"], body, border_radius=5)
    # brick courses
    for y in range(body.y + 6, body.bottom, 8):
        pygame.draw.line(s, PAL["brick_d"], (body.x, y), (body.right, y), 1)
    # glowing furnace mouth
    mouth = pygame.Rect(0, 0, 22, 16)
    mouth.center = (TILE // 2, TILE // 2 + 6)
    pygame.draw.rect(s, PAL["ember"], mouth, border_radius=3)
    pygame.draw.rect(s, PAL["ember_hot"], mouth.inflate(-8, -8), border_radius=2)
    # chimney
    pygame.draw.rect(s, PAL["metal_d"], (TILE // 2 - 5, 4, 10, 12))
    return s


def draw_assembler(name) -> pygame.Surface:
    s = _new()
    body = pygame.Rect(8, 10, TILE - 16, TILE - 18)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=6)
    pygame.draw.rect(s, PAL["metal"], body, border_radius=6)
    pygame.draw.rect(s, PAL["metal_l"], (body.x, body.y, body.w, 7), border_radius=6)
    # gear emblem
    cx, cy = TILE // 2, TILE // 2 + 2
    pygame.draw.circle(s, PAL["hazard"], (cx, cy), 13)
    pygame.draw.circle(s, PAL["metal_d"], (cx, cy), 6)
    for k in range(8):
        a = k * math.pi / 4
        x = cx + int(15 * math.cos(a))
        y = cy + int(15 * math.sin(a))
        pygame.draw.circle(s, PAL["hazard"], (x, y), 3)
    pygame.draw.circle(s, PAL["outline"], (cx, cy), 13, 2)
    return s


def draw_boiler(name) -> pygame.Surface:
    """A squat steam boiler: metal tank, glowing firebox, chimney + steam puff."""
    s = _new()
    body = pygame.Rect(12, 22, TILE - 24, TILE - 34)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=8)
    pygame.draw.rect(s, PAL["metal"], body, border_radius=8)
    pygame.draw.rect(s, PAL["metal_l"], (body.x, body.y, body.w, 7), border_radius=8)
    fb = pygame.Rect(0, 0, body.w - 12, 8)
    fb.center = (TILE // 2, body.bottom - 5)
    pygame.draw.rect(s, PAL["ember"], fb, border_radius=2)
    pygame.draw.rect(s, PAL["ember_hot"], fb.inflate(-6, -3), border_radius=2)
    pygame.draw.rect(s, PAL["metal_d"], (TILE // 2 - 4, 8, 8, 16))       # chimney
    pygame.draw.circle(s, (210, 212, 216), (TILE // 2, 8), 5)            # steam
    pygame.draw.circle(s, (228, 230, 234), (TILE // 2 + 3, 5), 3)
    return s


def draw_nuclear_plant(name) -> pygame.Surface:
    """A reactor: a glowing-green containment dome (bright so it reads on the grey concourse)
    with a radiation trefoil - the unmistakable power backbone of the endgame base."""
    s = _new()
    cx, cy = TILE // 2, TILE // 2 + 2
    # soft green glow halo so it pops against grey pavement
    for rr, a in ((28, 45), (23, 80), (18, 130)):
        halo = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pygame.draw.circle(halo, (*PAL["glow"], a), (cx, cy), rr)
        s.blit(halo, (0, 0))
    dome = pygame.Rect(9, 14, TILE - 18, TILE - 20)
    pygame.draw.ellipse(s, PAL["outline"], dome.inflate(2, 2))
    pygame.draw.ellipse(s, PAL["uranium_d"], dome)                 # green dome (not grey)
    pygame.draw.ellipse(s, PAL["uranium"], (dome.x, dome.y, dome.w, dome.h // 2))
    pygame.draw.circle(s, PAL["glow"], (cx, cy), 11)               # bright core
    pygame.draw.circle(s, (235, 255, 210), (cx, cy), 6)
    for k in range(3):                                             # radiation trefoil
        a = k * 2 * math.pi / 3 - math.pi / 2
        x, y = cx + int(9 * math.cos(a)), cy + int(9 * math.sin(a))
        pygame.draw.polygon(s, PAL["outline"], [
            (cx, cy),
            (x + int(6 * math.cos(a + 0.55)), y + int(6 * math.sin(a + 0.55))),
            (x + int(6 * math.cos(a - 0.55)), y + int(6 * math.sin(a - 0.55)))])
    pygame.draw.circle(s, PAL["outline"], (cx, cy), 3)
    return s


def draw_hq(name) -> pygame.Surface:
    s = _new()
    base = pygame.Rect(6, 14, TILE - 12, TILE - 20)
    pygame.draw.rect(s, PAL["outline"], base.inflate(2, 2), border_radius=4)
    pygame.draw.rect(s, PAL["steel"], base, border_radius=4)
    pygame.draw.rect(s, PAL["steel_l"], (base.x, base.y, base.w, 9), border_radius=4)
    # windows
    r = _rng(name)
    for gx in range(base.x + 8, base.right - 8, 12):
        for gy in range(base.y + 14, base.bottom - 8, 12):
            col = PAL["glass"] if r.random() > 0.3 else _darken(PAL["glass"], 60)
            pygame.draw.rect(s, col, (gx, gy, 7, 7))
    # flag
    pygame.draw.line(s, PAL["metal_d"], (TILE // 2, 6), (TILE // 2, 16), 2)
    pygame.draw.polygon(s, PAL["loco_red"], [(TILE // 2, 6), (TILE // 2 + 12, 9), (TILE // 2, 12)])
    return s


def draw_train_stop(name) -> pygame.Surface:
    s = _new()
    # pole
    pygame.draw.line(s, PAL["metal_d"], (TILE // 2, TILE - 6), (TILE // 2, 14), 4)
    pygame.draw.circle(s, PAL["metal_d"], (TILE // 2, TILE - 6), 5)
    # sign
    sign = pygame.Rect(TILE // 2 - 2, 12, 22, 16)
    pygame.draw.rect(s, PAL["outline"], sign.inflate(2, 2), border_radius=3)
    pygame.draw.rect(s, PAL["loco_red"], sign, border_radius=3)
    pygame.draw.rect(s, PAL["ember_hot"], (sign.x + 3, sign.y + 4, 16, 3))
    pygame.draw.rect(s, PAL["ember_hot"], (sign.x + 3, sign.y + 9, 11, 3))
    return s


def draw_locomotive(name, body_c=None, body_d=None) -> pygame.Surface:
    """Top-down, nose pointing +X (right). Renderer rotates to travel heading.
    `body_c`/`body_d` recolour the hull for per-train variety."""
    body_c = body_c or PAL["loco_red"]
    body_d = body_d or PAL["loco_red_d"]
    s = _new()
    body = pygame.Rect(6, 16, TILE - 12, TILE - 32)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=10)
    pygame.draw.rect(s, body_c, body, border_radius=10)
    pygame.draw.rect(s, body_d, (body.x, body.centery, body.w, body.h // 2), border_radius=10)
    # nose taper
    pygame.draw.polygon(s, body_d, [(body.right, body.y + 4),
                        (body.right + 6, TILE // 2), (body.right, body.bottom - 4)])
    # cabin window
    pygame.draw.rect(s, PAL["glass"], (body.x + 6, body.y + 6, 14, body.h - 12), border_radius=3)
    # headlight
    pygame.draw.circle(s, PAL["ember_hot"], (body.right + 3, TILE // 2), 3)
    return s


def draw_wagon(name, body_c=None, body_d=None) -> pygame.Surface:
    body_c = body_c or PAL["wagon_brown"]
    body_d = body_d or PAL["wagon_brown_d"]
    s = _new()
    body = pygame.Rect(4, 16, TILE - 8, TILE - 32)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=5)
    pygame.draw.rect(s, body_c, body, border_radius=5)
    # ribs
    for x in range(body.x + 8, body.right - 4, 10):
        pygame.draw.line(s, body_d, (x, body.y + 2), (x, body.bottom - 2), 2)
    pygame.draw.rect(s, body_d, (body.x, body.y, body.w, 4))
    return s


def draw_rocket(name) -> pygame.Surface:
    """A cargo rocket pointing UP (nose at top) - the renderer draws it ascending
    from the base without rotating it."""
    s = _new()
    cx = TILE // 2
    # body (tall capsule)
    body = pygame.Rect(cx - 9, 16, 18, 36)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=8)
    pygame.draw.rect(s, PAL["steel_l"], body, border_radius=8)
    pygame.draw.rect(s, PAL["steel"], (cx, body.y, body.w // 2, body.h), border_radius=8)
    # nose cone
    pygame.draw.polygon(s, PAL["outline"], [(cx, 4), (body.x - 1, body.y + 4), (body.right + 1, body.y + 4)])
    pygame.draw.polygon(s, PAL["loco_red"], [(cx, 7), (body.x + 1, body.y + 3), (body.right - 1, body.y + 3)])
    # window
    pygame.draw.circle(s, PAL["glass"], (cx, body.y + 12), 4)
    pygame.draw.circle(s, PAL["outline"], (cx, body.y + 12), 4, 1)
    # fins
    pygame.draw.polygon(s, PAL["loco_red_d"], [(body.x, body.bottom - 10), (body.x - 7, body.bottom + 2), (body.x, body.bottom)])
    pygame.draw.polygon(s, PAL["loco_red_d"], [(body.right, body.bottom - 10), (body.right + 7, body.bottom + 2), (body.right, body.bottom)])
    # engine bell
    pygame.draw.rect(s, PAL["metal_d"], (cx - 6, body.bottom - 2, 12, 6), border_radius=2)
    return s


def draw_scout(name) -> pygame.Surface:
    s = _new()
    body = pygame.Rect(14, 18, TILE - 28, TILE - 30)
    pygame.draw.rect(s, PAL["outline"], body.inflate(2, 2), border_radius=6)
    pygame.draw.rect(s, PAL["scout_yellow"], body, border_radius=6)
    pygame.draw.rect(s, PAL["scout_yellow_d"], (body.x, body.centery, body.w, body.h // 2), border_radius=6)
    # wheels
    for wy in (body.y - 3, body.bottom - 3):
        pygame.draw.rect(s, PAL["coal"], (body.x - 2, wy, 6, 6), border_radius=2)
        pygame.draw.rect(s, PAL["coal"], (body.right - 4, wy, 6, 6), border_radius=2)
    # dome + antenna
    pygame.draw.circle(s, PAL["glass"], (TILE // 2, TILE // 2), 6)
    pygame.draw.line(s, PAL["metal_d"], (TILE // 2, TILE // 2 - 6), (TILE // 2 + 6, 8), 2)
    pygame.draw.circle(s, PAL["loco_red"], (TILE // 2 + 6, 8), 2)
    return s


def draw_animal(name) -> pygame.Surface:
    """Top-down critter, facing +X (right). Renderer rotates to heading."""
    s = _new()
    body = pygame.Rect(0, 0, 34, 22)
    body.center = (TILE // 2 - 2, TILE // 2)
    pygame.draw.ellipse(s, PAL["outline"], body.inflate(3, 3))
    pygame.draw.ellipse(s, PAL["wood"], body)
    pygame.draw.ellipse(s, PAL["wood_d"], (body.x, body.centery, body.w, body.h // 2))
    # legs
    for lx in (body.x + 7, body.right - 10):
        pygame.draw.rect(s, PAL["wood_d"], (lx, body.y - 3, 4, 5))
        pygame.draw.rect(s, PAL["wood_d"], (lx, body.bottom - 2, 4, 5))
    # head + eye
    hx, hy = body.right + 2, body.centery
    pygame.draw.circle(s, PAL["outline"], (hx, hy), 9)
    pygame.draw.circle(s, PAL["wood"], (hx, hy), 8)
    pygame.draw.circle(s, (235, 230, 220), (hx + 3, hy - 2), 2)
    pygame.draw.circle(s, PAL["outline"], (hx + 3, hy - 2), 1)
    # little horns
    pygame.draw.line(s, PAL["stone_d"], (hx + 2, hy - 7), (hx + 6, hy - 11), 2)
    return s


def draw_tree(name) -> pygame.Surface:
    s = _new()
    r = _rng(name)
    pygame.draw.rect(s, PAL["wood_d"], (TILE // 2 - 3, TILE // 2, 6, 18))
    for _ in range(5):
        cx = TILE // 2 + r.randint(-8, 8)
        cy = TILE // 2 - 6 + r.randint(-8, 8)
        pygame.draw.circle(s, PAL["leaf_d"], (cx, cy), r.randint(8, 12))
    for _ in range(5):
        cx = TILE // 2 + r.randint(-7, 7)
        cy = TILE // 2 - 8 + r.randint(-6, 6)
        pygame.draw.circle(s, PAL["leaf"], (cx, cy), r.randint(5, 9))
    return s


def draw_rock(name) -> pygame.Surface:
    s = _new()
    r = _rng(name)
    pts = []
    for k in range(7):
        a = k * (2 * math.pi / 7)
        rad = r.randint(12, 20)
        pts.append((TILE // 2 + int(rad * math.cos(a)), TILE // 2 + int(rad * math.sin(a))))
    pygame.draw.polygon(s, PAL["outline"], pts)
    inner = [(x, y - 2) for x, y in pts]
    pygame.draw.polygon(s, PAL["stone"], inner)
    pygame.draw.polygon(s, PAL["stone_d"], inner[:4])
    return s


_DRAW = {
    "grass": draw_grass,
    "ore_iron": lambda n: _ore(n, PAL["iron"], PAL["iron_d"]),
    "ore_copper": lambda n: _ore(n, PAL["copper"], PAL["copper_d"]),
    "ore_coal": lambda n: _ore(n, PAL["coal"], PAL["coal_d"]),
    "ore_stone": lambda n: _ore(n, PAL["stone"], PAL["stone_d"]),
    "ore_uranium": lambda n: _ore(n, PAL["uranium"], PAL["uranium_d"]),
    "mining_drill": draw_mining_drill,
    "smelter": draw_smelter,
    "assembler": draw_assembler,
    "boiler": draw_boiler,
    "nuclear_plant": draw_nuclear_plant,
    "hq": draw_hq,
    "train_stop": draw_train_stop,
    "locomotive": draw_locomotive,
    "locomotive_2": lambda n: draw_locomotive(n, PAL["loco_blue"], PAL["loco_blue_d"]),
    "locomotive_3": lambda n: draw_locomotive(n, PAL["loco_green"], PAL["loco_green_d"]),
    "locomotive_4": lambda n: draw_locomotive(n, PAL["loco_dark"], PAL["loco_dark_d"]),
    "wagon": draw_wagon,
    "wagon_2": lambda n: draw_wagon(n, PAL["wagon_steel"], PAL["wagon_steel_d"]),
    "wagon_3": lambda n: draw_wagon(n, PAL["wagon_olive"], PAL["wagon_olive_d"]),
    "wagon_4": lambda n: draw_wagon(n, PAL["wagon_gray"], PAL["wagon_gray_d"]),
    "rocket": draw_rocket,
    "scout": draw_scout,
    "animal": draw_animal,
    "tree": draw_tree,
    "rock": draw_rock,
}


def render_sprite(name: str) -> pygame.Surface:
    if name not in _DRAW:
        raise KeyError(f"unknown sprite {name!r}")
    return _DRAW[name](name)


def ensure_assets(sprite_dir: str, force: bool = False) -> list[str]:
    """Generate any missing sprite PNGs into `sprite_dir`. Returns names written.

    Import- and runtime-safe: relies only on pygame Surface drawing (works without a
    window) and never calls pygame.init()/quit(), so it won't disturb a running game.
    """
    os.makedirs(sprite_dir, exist_ok=True)
    written = []
    for name in SPRITE_NAMES:
        path = os.path.join(sprite_dir, f"{name}.png")
        if force or not os.path.exists(path):
            surf = render_sprite(name)
            pygame.image.save(surf, path)
            written.append(name)
    return written


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    if not pygame.get_init():
        pygame.init()
    here = os.path.dirname(os.path.abspath(__file__))
    sprite_dir = os.path.join(here, "sprites")
    written = ensure_assets(sprite_dir, force=force)
    print(f"[generate_assets] {len(written)} sprite(s) written to {sprite_dir}")
    for n in written:
        print(f"  - {n}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
