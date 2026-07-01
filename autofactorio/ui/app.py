"""Main application: window, input handling, and the per-frame update/draw loop.

Controls:
  mouse wheel        zoom in/out at the cursor
  right-drag / WASD / arrows   pan
  F                  follow the scout
  Space              pause / resume
  + / -              game speed
  I                  toggle detail panel
  L                  toggle comms console
  N                  force a director decision now
  F5 / F9            quicksave / quickload
  Esc                quit
  (top-right button) New game — reset timer/map/resources (click twice to confirm)

The game autosaves on exit and auto-resumes on the next launch.
"""

from __future__ import annotations

import os

import pygame

from .. import balance
from ..engine.simulation import Simulation
from ..ai.director import Director
from .assets import Assets
from .camera import Camera
from .renderer import Renderer
from .hud import Hud, _fmt_time
from .console import Console
from .minimap import Minimap

HINT = ("wheel: zoom   right-drag/WASD: pan   click minimap: jump   F: follow scout   "
        "Space: pause   +/-: speed   I: details   L: comms   M: map   F5/F9: save/load   Esc: quit")

_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "saves")
SAVE_PATH = os.path.join(_SAVE_DIR, "quicksave.json")
# Written automatically on quit and loaded automatically on startup (resume).
AUTOSAVE_PATH = os.path.join(_SAVE_DIR, "autosave.json")


class App:
    def __init__(self, config):
        self.config = config
        pygame.init()
        pygame.display.set_caption("AutoFactorio")
        flags = pygame.RESIZABLE | (pygame.FULLSCREEN if config.display.fullscreen else 0)
        self.screen = pygame.display.set_mode((config.display.width, config.display.height), flags)
        self.clock = pygame.time.Clock()

        self.assets = Assets()
        self.sim = Simulation(config)
        self.director = Director(self.sim, config)
        self.renderer = Renderer(self.assets)
        font = pygame.font.SysFont("consolas,couriernew,monospace", 16)
        small = pygame.font.SysFont("consolas,couriernew,monospace", 14)
        big = pygame.font.SysFont("consolas,couriernew,monospace", 22, bold=True)
        self.hud = Hud(font, small, big)
        self.console = Console(small, lines=8)
        self.minimap = Minimap()
        self.hint_font = small

        w, h = self.screen.get_size()
        self.cam = Camera(0, 0, 20.0, w, h)
        self.follow_scout = False
        self.follow_selected = False
        self.selected = None            # ('train', id) | ('field', id) | None
        self.show_console = True
        self.show_detail = False
        self.show_minimap = True
        self.running = True
        self.speed_idx = balance.GAME_SPEEDS.index(balance.DEFAULT_GAME_SPEED)
        self._new_game_armed_until = 0   # ms; New-game button needs a confirm click
        self.frame_dt = 0.0              # effective sim dt this frame (for particles)

    # ---- loop -------------------------------------------------------------
    def run(self) -> None:
        try:
            while self.running:
                dt = self.clock.tick(self.config.display.fps) / 1000.0
                self.frame_dt = 0.0 if self.sim.paused else dt * self.sim.speed
                self._events()
                self._held_keys(dt)
                self._apply_follow()
                self.sim.tick(dt)
                self.director.update()
                self._draw()
                pygame.display.flip()
        finally:
            self._autosave()
            pygame.quit()

    def _autosave(self) -> None:
        """Persist the game on shutdown so the next launch resumes it."""
        try:
            os.makedirs(_SAVE_DIR, exist_ok=True)
            self.sim.save(AUTOSAVE_PATH)
        except Exception:
            pass            # never let a failed autosave stop a clean exit

    def _new_game(self) -> None:
        """Reset the timer, world and resources back to the very start."""
        self.sim = Simulation(self.config)
        self.director = Director(self.sim, self.config)
        self.selected = None
        self.follow_scout = False
        self.follow_selected = False
        self.speed_idx = balance.GAME_SPEEDS.index(balance.DEFAULT_GAME_SPEED)
        self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]
        self.cam.center_on(0, 0)
        self.sim.log("New game: timer, map and resources reset to the start.")

    def _click_new_game(self) -> None:
        now = pygame.time.get_ticks()
        if now < self._new_game_armed_until:        # second click within window
            self._new_game_armed_until = 0
            self._new_game()
        else:
            self._new_game_armed_until = now + 3000
            self.sim.log("New game armed — click the button again within 3s to confirm.")

    # ---- input ------------------------------------------------------------
    def _events(self) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode((e.w, e.h), pygame.RESIZABLE)
                self.cam.resize(e.w, e.h)
            elif e.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                self.cam.zoom_at(mx, my, 1.12 ** e.y)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                btn = self.hud.button_rects.get("new_game")
                if btn is not None and btn.collidepoint(e.pos):
                    self._click_new_game()
                elif self.show_minimap and self.minimap.handle_click(e.pos, self.screen, self.cam, self.sim):
                    self.follow_scout = False
                    self.follow_selected = False
                else:
                    self._pick(e.pos)
            elif e.type == pygame.MOUSEMOTION:
                if e.buttons[2]:                       # right-button drag = grab pan
                    self.cam.pan_pixels(e.rel[0], e.rel[1])
                    self.follow_scout = False
            elif e.type == pygame.KEYDOWN:
                self._keydown(e)

    def _keydown(self, e) -> None:
        if e.key == pygame.K_ESCAPE:
            self.running = False
        elif e.key == pygame.K_SPACE:
            self.sim.paused = not self.sim.paused
        elif e.key == pygame.K_f:
            self.follow_scout = not self.follow_scout
            if self.follow_scout:
                self.follow_selected = False
        elif e.key == pygame.K_i:
            self.show_detail = not self.show_detail
        elif e.key == pygame.K_l:
            self.show_console = not self.show_console
        elif e.key == pygame.K_m:
            self.show_minimap = not self.show_minimap
        elif e.key == pygame.K_n:
            self.director.force_decision()
        elif e.key == pygame.K_F5:
            self.sim.save(SAVE_PATH)
        elif e.key == pygame.K_F9:
            if os.path.exists(SAVE_PATH):
                ok, _ = self.sim.load(SAVE_PATH)
                if ok:
                    self.director.reset()
            else:
                self.sim.log("No quicksave found (press F5 to save).")
        elif e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.speed_idx = min(self.speed_idx + 1, len(balance.GAME_SPEEDS) - 1)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]
        elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.speed_idx = max(self.speed_idx - 1, 0)
            self.sim.speed = balance.GAME_SPEEDS[self.speed_idx]

    def _pick(self, pos) -> None:
        """Select the nearest train (then field, then ore patch) to a world click;
        deselect on a miss. Discovered patches can be inspected whether or not
        they're claimed."""
        wx, wy = self.cam.screen_to_world(*pos)
        best = None
        best_d = 4.0 ** 2                     # within ~4 tiles of a loco
        for t in self.sim.trains.values():
            poses = t.car_poses()
            if not poses:
                continue
            d = (poses[0][0] - wx) ** 2 + (poses[0][1] - wy) ** 2
            if d < best_d:
                best_d, best = d, ("train", t.id)
        if best is not None:
            self.selected = best
            self.follow_selected = True
            self.follow_scout = False
            return
        if wx * wx + wy * wy <= 8.0 ** 2:          # the home base (HQ + factory ring)
            self.selected = ("base", 0)
            self.follow_selected = False
            return
        for f in self.sim.fields.values():
            rad = (f.patch.radius + 3) ** 2
            if (f.patch.cx - wx) ** 2 + (f.patch.cy - wy) ** 2 < rad:
                self.selected = ("field", f.id)
                self.follow_selected = False
                self.cam.center_on(f.patch.cx, f.patch.cy)
                return
        # unclaimed (or any discovered) ore patch
        patch = None
        pbest = None
        for p in self.sim.world.patches:
            if not p.discovered:
                continue
            d = (p.cx - wx) ** 2 + (p.cy - wy) ** 2
            if d <= (p.radius + 2) ** 2 and (pbest is None or d < pbest):
                pbest, patch = d, p
        if patch is not None:
            self.selected = ("patch", patch.id)
            self.follow_selected = False
            return
        self.selected = None
        self.follow_selected = False

    def _apply_follow(self) -> None:
        if self.follow_selected and self.selected and self.selected[0] == "train":
            t = self.sim.trains.get(self.selected[1])
            if t:
                poses = t.car_poses()
                if poses:
                    self.cam.center_on(poses[0][0], poses[0][1])
                    return
            self.follow_selected = False       # train gone (e.g. salvaged)
        if self.follow_scout:
            self.cam.center_on(*self.sim.scout.pos)

    def _held_keys(self, dt: float) -> None:
        k = pygame.key.get_pressed()
        pan = (700.0 * dt) / self.cam.zoom
        dx = dy = 0.0
        if k[pygame.K_a] or k[pygame.K_LEFT]:
            dx -= pan
        if k[pygame.K_d] or k[pygame.K_RIGHT]:
            dx += pan
        if k[pygame.K_w] or k[pygame.K_UP]:
            dy -= pan
        if k[pygame.K_s] or k[pygame.K_DOWN]:
            dy += pan
        if dx or dy:
            self.cam.pan_world(dx, dy)
            self.follow_scout = False

    # ---- draw -------------------------------------------------------------
    def _draw(self) -> None:
        self.renderer.draw(self.screen, self.cam, self.sim, self.selected, self.frame_dt)
        armed = pygame.time.get_ticks() < self._new_game_armed_until
        self.hud.draw(self.screen, self.sim, self.director, self.show_detail, new_game_armed=armed)
        if self.show_minimap:
            self.minimap.draw(self.screen, self.cam, self.sim)
        self._draw_selection_readout()
        if self.show_console:
            self.console.draw(self.screen, self.sim)
        else:
            hint = self.hint_font.render(HINT, True, (150, 156, 166))
            self.screen.blit(hint, (10, self.screen.get_height() - 22))
        self.hud.draw_tooltip(self.screen)        # drawn last so it sits on top

    def _draw_base_panel(self) -> None:
        eco = self.sim.economy
        lines = [("HOME BASE", True)]
        lines.append((f"Factories: {eco.furnaces} furnaces, {eco.assemblers} assemblers", False))
        lines.append((f"Robots: {len(self.sim.robots)}/{self.sim.research.max_robots}"
                      f"     Research: Tech L{self.sim.research.level}", False))
        lines.append(("", False))
        # POWER: buildings burn fuel to run; show supply vs demand, burn rate, and how
        # long the fuel in stock lasts with no refills.
        lines.append(("POWER", True))
        low = eco.power_factor < 0.99
        lines.append((f"  Generation {eco.power_supplied:.1f} / demand {eco.power_demand:.1f} e/s"
                      + ("   LOW POWER!" if low else ""), False))
        tte = eco.seconds_to_empty()
        tte_str = "never" if tte == float("inf") else _fmt_time(tte)
        lines.append((f"  Burning {eco.fuel_rate:.1f}/s {balance.DISPLAY_NAME.get(eco.burning, eco.burning)}"
                      f"   empty in {tte_str}", False))
        lines.append(("", False))
        lines.append(("STORAGE", True))
        order = ["iron_ore", "copper_ore", "stone", "iron_plate", "copper_plate",
                 "steel_plate", "stone_brick", "coal",
                 "compressed_coal", "refined_fuel", "nuclear_fuel", "fusion_fuel",
                 "electronic_circuit", "iron_gear",
                 "science_pack", "rail", "rail_signal", "chain_signal", "train_stop",
                 "burner_drill", "electric_drill", "stone_furnace", "assembler",
                 "locomotive", "cargo_wagon", "robot"]
        for k in order:
            v = eco.inv.get(k, 0)
            if v:
                # storage is finite and per-resource: show actual/cap for capped
                # items (flag the full ones); uncapped intermediates show bare.
                cap = eco.cap_of(k)
                if cap is not None:
                    val = f"{v}/{cap}" + ("  FULL" if v >= cap else "")
                else:
                    val = f"{v}"
                lines.append((f"  {balance.DISPLAY_NAME.get(k, k):16s}{val}", False))
        lines.append(("", False))
        lines.append((f"Produced: {eco.total_smelted} smelted, {eco.total_crafted} crafted", False))
        lines.append((f"Delivered home: {self.sim.delivered_total}", False))

        ph = len(lines) * 16 + 14
        panel = pygame.Surface((300, ph), pygame.SRCALPHA)
        panel.fill((10, 12, 17, 230))
        self.screen.blit(panel, (8, 72))
        pygame.draw.rect(self.screen, (70, 76, 86), (8, 72, 300, ph), 1)
        y = 80
        for text, head in lines:
            if head:
                col = (120, 190, 240)
            elif text.endswith("FULL"):
                col = (235, 170, 90)              # storage at capacity
            else:
                col = (228, 232, 238)
            self.screen.blit(self.hint_font.render(text, True, col), (16, y))
            y += 16

    def _draw_selection_readout(self) -> None:
        if not self.selected:
            return
        kind, sid = self.selected
        if kind == "base":
            self._draw_base_panel()
            return
        text = None
        if kind == "train":
            t = self.sim.trains.get(sid)
            if t:
                st = "following" if self.follow_selected else "selected"
                text = (f"Train #{sid} [{st}]  cargo {t.cargo_total()}/{t.capacity}  "
                        f"fuel {t.fuel_seconds:.0f}s  {t.state}"
                        + ("  STALLED" if t.stalled else ""))
        elif kind == "field":
            f = self.sim.fields.get(sid)
            if f:
                text = (f"Field #{sid}  {f.patch.ore}  drills {f.drills}  "
                        f"buffer {f.buffer}  reserve {int(f.patch.reserve)}")
        elif kind == "patch":
            p = self.sim.world.patch_by_id(sid)
            if p:
                import math
                status = "depleted" if p.depleted else ("claimed" if p.claimed else "unclaimed")
                pct = int(100 * p.reserve / p.max_reserve) if p.max_reserve else 0
                text = (f"{p.ore.replace('_', ' ').title()} patch #{sid} [{status}]  "
                        f"reserve {int(p.reserve)}/{p.max_reserve} ({pct}%)  "
                        f"{int(math.hypot(p.cx, p.cy))} tiles from base")
        if not text:
            self.selected = None
            return
        surf = self.hint_font.render(text, True, (250, 240, 160))
        y = self.screen.get_height() - (self.console.lines * 18 + 16) - 22 if self.show_console \
            else self.screen.get_height() - 40
        bg = pygame.Surface((surf.get_width() + 12, 20), pygame.SRCALPHA)
        bg.fill((10, 12, 17, 200))
        self.screen.blit(bg, (8, y - 2))
        self.screen.blit(surf, (12, y))
