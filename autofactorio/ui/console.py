"""Bottom comms console: the running log of scout finds and director decisions
(every report -> reasoning -> action exchange), timestamped and color-coded.
"""

from __future__ import annotations

import pygame

PANEL = (10, 12, 17)
DEFAULT = (200, 206, 214)
AI = (130, 195, 245)
AUTO = (175, 200, 150)
ACTION = (150, 210, 170)
FAIL = (224, 150, 120)
SCOUT = (210, 195, 120)
DIM = (130, 136, 146)


def _color(text: str):
    if text.startswith("[AI]"):
        return AI
    if text.startswith("[auto]"):
        return AUTO
    if text.startswith("[director]"):
        return DIM
    if text.strip().startswith("OK"):
        return ACTION
    if text.strip().startswith("--") or text.strip().startswith("!"):
        return FAIL
    if "Scout" in text:
        return SCOUT
    return DEFAULT


class Console:
    def __init__(self, font: pygame.font.Font, lines: int = 8):
        self.font = font
        self.lines = lines

    def draw(self, screen, sim) -> None:
        w = screen.get_width()
        h = screen.get_height()
        ph = self.lines * 18 + 16
        panel = pygame.Surface((w, ph), pygame.SRCALPHA)
        panel.fill((*PANEL, 205))
        screen.blit(panel, (0, h - ph))

        title = self.font.render("COMMS — director & scout log  (L to hide)", True, DIM)
        screen.blit(title, (10, h - ph + 4))

        events = sim.events[-self.lines:]
        y = h - ph + 22
        for t, text in events:
            mm, ss = divmod(int(t), 60)
            ts = self.font.render(f"{mm:02d}:{ss:02d}", True, DIM)
            screen.blit(ts, (10, y))
            body = text if len(text) < 150 else text[:147] + "..."
            screen.blit(self.font.render(body, True, _color(text)), (64, y))
            y += 18
