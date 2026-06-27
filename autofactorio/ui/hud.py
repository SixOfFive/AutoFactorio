"""Top HUD: key inventory, network stats, game speed, and director status."""

from __future__ import annotations

import pygame

PANEL = (14, 16, 22)
TEXT = (228, 232, 238)
DIM = (150, 156, 166)
GOOD = (120, 220, 130)
WARN = (235, 180, 70)
BAD = (232, 90, 76)
AI = (120, 190, 240)

_INV = [
    ("iron_plate", "Fe"), ("copper_plate", "Cu"), ("steel_plate", "St"),
    ("stone", "Sto"), ("coal", "Coal"), ("rail", "Rail"),
    ("electric_drill", "Drill"), ("locomotive", "Loco"), ("cargo_wagon", "Wagon"),
]


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1e6:.1f}M"
    if n >= 10_000:
        return f"{n/1e3:.0f}k"
    if n >= 1_000:
        return f"{n/1e3:.1f}k"
    return str(int(n))


class Hud:
    def __init__(self, font: pygame.font.Font, small: pygame.font.Font, big: pygame.font.Font):
        self.font = font
        self.small = small
        self.big = big

    def draw(self, screen, sim, director, detailed: bool) -> None:
        w = screen.get_width()
        bar = pygame.Surface((w, 64), pygame.SRCALPHA)
        bar.fill((*PANEL, 215))
        screen.blit(bar, (0, 0))

        # row 1: inventory chips
        x = 12
        for key, label in _INV:
            val = sim.economy.inv.get(key, 0)
            chip = f"{label} {_fmt(val)}"
            col = TEXT
            if key == "coal":
                col = BAD if val < 150 else WARN if val < 400 else GOOD
            surf = self.small.render(chip, True, col)
            screen.blit(surf, (x, 8))
            x += surf.get_width() + 18

        # row 2: stats
        s = sim.stats()
        mm, ss = divmod(int(sim.time), 60)
        stats = (f"⏱ {mm:02d}:{ss:02d}   Fields {s['fields']}   Trains {s['trains']}"
                 f"   Rail {_fmt(s['rail_tiles'])}t   Delivered {_fmt(s['delivered'])}"
                 f"   Patches {s['discovered_patches']} found / {s['claimable_patches']} open")
        screen.blit(self.small.render(stats, True, DIM), (12, 34))

        # right side: speed + director
        spd = f"{'PAUSED' if sim.paused else f'{sim.speed:g}x'}"
        spd_s = self.font.render(spd, True, WARN if sim.paused else TEXT)
        screen.blit(spd_s, (w - spd_s.get_width() - 14, 8))

        src = "LLM" if director.source == "llm" else "AUTO"
        col = AI if director.source == "llm" else DIM
        if director.use_llm and not director.online:
            src = "LLM offline → AUTO"
            col = WARN
        ds = self.small.render(f"Director: {src}", True, col)
        screen.blit(ds, (w - ds.get_width() - 14, 38))

        if s["stalled_trains"]:
            warn = self.small.render(f"⚠ {s['stalled_trains']} train(s) out of fuel", True, BAD)
            screen.blit(warn, (w // 2 - warn.get_width() // 2, 44))

        if detailed:
            self._panel(screen, sim, director)

    def _panel(self, screen, sim, director):
        w = screen.get_width()
        lines = ["INVENTORY"]
        for k in sorted(sim.economy.inv):
            v = sim.economy.inv[k]
            if v:
                lines.append(f"  {k:18s} {_fmt(v):>7}")
        lines.append("")
        lines.append("FIELDS")
        for f in sim.fields.values():
            lines.append(f"  #{f.id} {f.patch.ore[:6]:6s} drills {f.drills} "
                         f"buf {_fmt(f.buffer)} res {_fmt(int(f.patch.reserve))}")
        ph = len(lines) * 16 + 16
        panel = pygame.Surface((290, ph), pygame.SRCALPHA)
        panel.fill((*PANEL, 225))
        screen.blit(panel, (8, 72))          # left side; minimap owns the right
        y = 80
        for ln in lines:
            col = AI if ln in ("INVENTORY", "FIELDS") else TEXT
            screen.blit(self.small.render(ln, True, col), (16, y))
            y += 16
