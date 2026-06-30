"""Top HUD: key inventory, network stats, game speed, and director status.

Every value on the bar is a hover zone: mousing over it shows a tooltip with the
item's/stat's full name and what it is for (see draw_tooltip)."""

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

# (title, description) shown on hover. Keys match inventory items + stat ids below.
INFO = {
    "iron_plate": ("Iron plate", "Smelted from iron ore. The backbone material — rails, gears, "
                                 "circuits, drills, trains and almost everything need it."),
    "copper_plate": ("Copper plate", "Smelted from copper ore. Drawn into copper cable for "
                                     "electronic circuits."),
    "steel_plate": ("Steel plate", "Smelted from iron plate (5 plates → 1 steel). Used for rails, "
                                   "locomotives, wagons and robots."),
    "stone": ("Stone", "Mined raw. Crafts into rails and stone furnaces."),
    "coal": ("Coal", "Mined raw. Fuels every locomotive — trains burn it to move. Robots can haul "
                     "extra as a slow last resort when it runs low."),
    "rail": ("Rail", "Track pieces. Robots drive out and lay these to connect new mining fields "
                     "to the base."),
    "electric_drill": ("Electric drill", "Mines an ore patch. More drills per field = faster "
                                         "mining. Robots place them when building a field."),
    "locomotive": ("Locomotive", "Pulls a train and burns coal. One per mining-field loop."),
    "cargo_wagon": ("Cargo wagon", "Hauls ore from a field to the base (2 per train by default). "
                                   "Research increases its capacity."),
    "time": ("Elapsed time", "How long this game has been running (in-game time). "
                             "Persists across save/load; the New game button resets it."),
    "new_game": ("New game", "Reset the timer, map and resources back to the very start. "
                             "Click once to arm, then click again within 3s to confirm."),
    "fields": ("Mining fields", "Active fields mining ore. Robots build new ones and tear down "
                                "exhausted ones."),
    "trains": ("Trains", "Locomotives hauling ore from fields to the base on one-way loops."),
    "rail_stat": ("Rail network", "Total length of track currently laid, in tiles."),
    "delivered": ("Ore delivered", "Total ore unloaded at the base so far."),
    "robots": ("Robots", "Up to 3. They build/dismantle fields, repair trains, fight wildlife, "
                         "gather emergency fuel and explore."),
    "animals": ("Wildlife", "Herds that wander and can spawn in the fog. Robots cull them and "
                            "trains crush them; they only fight back if a robot is replaceable."),
    "tech": ("Research", "Current tech level (up to 1000) and the next tech in progress. Each "
                        "level compounds the whole economy — mining, smelting, crafting, storage, "
                        "construction — so it snowballs into the hundreds."),
    "ships": ("Orbital trade", "Cargo rockets launched from the base once Spaceflight is researched. "
                              "Each consumes a payload and trades it back for science, accelerating research."),
    "speed": ("Game speed", "Simulation speed. Press + / - to change, Space to pause."),
    "director": ("Director", "The AI making expansion decisions — the LLM when reachable, else the "
                            "built-in heuristic (it auto-reconnects)."),
}


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1e6:.1f}M"
    if n >= 10_000:
        return f"{n/1e3:.0f}k"
    if n >= 1_000:
        return f"{n/1e3:.1f}k"
    return str(int(n))


def _fmt_time(secs: float) -> str:
    s = int(secs)
    h, r = divmod(s, 3600)
    m, ss = divmod(r, 60)
    return f"{h}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"


class Hud:
    def __init__(self, font: pygame.font.Font, small: pygame.font.Font, big: pygame.font.Font):
        self.font = font
        self.small = small
        self.big = big
        self._zones: list[tuple[pygame.Rect, str]] = []   # (rect, info-key)
        self.button_rects: dict[str, pygame.Rect] = {}    # clickable HUD buttons

    def draw(self, screen, sim, director, detailed: bool, new_game_armed: bool = False) -> None:
        w = screen.get_width()
        self._zones = []
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
            self._zones.append((pygame.Rect(x, 6, surf.get_width(), 20), key))
            x += surf.get_width() + 18

        # row 2: stats (each segment is its own hover zone)
        s = sim.stats()
        nxt = sim.research.next_tech()
        tech = f"Tech L{s['tech_level']}" + (f"→{nxt['name']}" if nxt else " (max)")
        segs = [
            (f"Time {_fmt_time(sim.time)}", "time"),
            (f"Fields {s['fields']}", "fields"),
            (f"Trains {s['trains']}", "trains"),
            (f"Rail {_fmt(s['rail_tiles'])}t", "rail_stat"),
            (f"Delivered {_fmt(s['delivered'])}", "delivered"),
            (f"Robots {s['robots']}/{s['max_robots']}", "robots"),
            (f"Animals {s['animals']} (killed {_fmt(s['kills'])})", "animals"),
            (tech, "tech"),
        ]
        if s.get("spaceflight"):
            segs.append((f"Ships {_fmt(s['ships_launched'])}", "ships"))
        x = 12
        for text, key in segs:
            surf = self.small.render(text, True, DIM)
            screen.blit(surf, (x, 34))
            self._zones.append((pygame.Rect(x, 32, surf.get_width(), 18), key))
            x += surf.get_width() + 16

        # right side, row 1: New game button, then speed to its left
        self.button_rects = {}
        label = "Confirm reset?" if new_game_armed else "New game"
        pad = 10
        bw = self.small.size(label)[0] + pad * 2
        bh = 22
        bx = w - bw - 12
        by = 6
        fill = WARN if new_game_armed else (52, 58, 70)
        pygame.draw.rect(screen, fill, (bx, by, bw, bh), border_radius=4)
        pygame.draw.rect(screen, (120, 128, 140), (bx, by, bw, bh), 1, border_radius=4)
        lab = self.small.render(label, True, (20, 16, 10) if new_game_armed else TEXT)
        screen.blit(lab, (bx + pad, by + (bh - lab.get_height()) // 2))
        btn = pygame.Rect(bx, by, bw, bh)
        self.button_rects["new_game"] = btn
        self._zones.append((btn, "new_game"))

        spd = "PAUSED" if sim.paused else f"{sim.speed:g}x"
        spd_s = self.font.render(spd, True, WARN if sim.paused else TEXT)
        sx = bx - spd_s.get_width() - 16
        screen.blit(spd_s, (sx, 8))
        self._zones.append((pygame.Rect(sx, 6, spd_s.get_width(), 22), "speed"))

        col = DIM if not director.use_llm else (AI if director.online else WARN)
        ds = self.small.render(director.status_text(), True, col)
        dx = w - ds.get_width() - 14
        screen.blit(ds, (dx, 38))
        self._zones.append((pygame.Rect(dx, 36, ds.get_width(), 18), "director"))

        if s["stalled_trains"]:
            warn = self.small.render(f"⚠ {s['stalled_trains']} train(s) out of fuel", True, BAD)
            screen.blit(warn, (w // 2 - warn.get_width() // 2, 50))

        if detailed:
            self._panel(screen, sim, director)

    # ---- tooltip (drawn last so it sits above everything) -----------------
    def draw_tooltip(self, screen) -> None:
        mx, my = pygame.mouse.get_pos()
        key = None
        for rect, k in self._zones:
            if rect.collidepoint(mx, my):
                key = k
                break
        if key is None or key not in INFO:
            return
        title, desc = INFO[key]
        width = 320
        lines = _wrap(self.small, desc, width - 20)
        title_s = self.font.render(title, True, TEXT)
        line_surfs = [self.small.render(ln, True, DIM) for ln in lines]
        h = 12 + title_s.get_height() + 4 + sum(ls.get_height() + 2 for ls in line_surfs)
        bx = min(mx + 14, screen.get_width() - width - 8)
        by = min(my + 18, screen.get_height() - h - 8)

        box = pygame.Surface((width, h), pygame.SRCALPHA)
        box.fill((10, 12, 17, 240))
        screen.blit(box, (bx, by))
        pygame.draw.rect(screen, (70, 76, 86), (bx, by, width, h), 1)
        screen.blit(title_s, (bx + 10, by + 8))
        y = by + 8 + title_s.get_height() + 4
        for ls in line_surfs:
            screen.blit(ls, (bx + 10, y))
            y += ls.get_height() + 2

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


def _wrap(font, text, max_w):
    words = text.split()
    lines, cur = [], ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if font.size(trial)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines
