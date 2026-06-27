"""The director: drives expansion decisions, LLM-first with heuristic fallback.

Threading model mirrors SimCity_LLM: the slow LLM call runs on a daemon worker
thread so the UI never stalls; resulting actions are applied on the main thread.

Connectivity: if the gateway errors (timeout / 5xx / 404 / refused), the director
switches fully to the INTERNAL heuristic so decisions never block on a dead
endpoint, then probes the LLM every RETRY_SECONDS on a background thread. On a
successful probe it resumes the AI director. Transitions are logged to the comms
console and the live status (with a retry countdown) shows in the HUD.
"""

from __future__ import annotations

import json
import threading
import time

from .client import LLMClient, LLMError
from .report import build_report
from .schema import validate
from .apply import apply_actions
from . import fallback

RETRY_SECONDS = 15.0

SYSTEM_PROMPT = """You are the logistics director of AutoFactorio, a train-network factory game.
Goal: grow a self-expanding rail empire. Mining fields auto-mine ore; one-way trains
haul it home; home factories smelt ore into plates and craft rails, drills, and rolling
stock. You decide how to SPEND that stockpile to expand. Track and routing are built
automatically and are always collision-free, so you only choose WHAT to build.

You receive a JSON game-state report. Reply with ONLY a JSON object:
{"reasoning": "<one short sentence>", "actions": [ <action>, ... ]}

Valid actions (use the exact "action" names and integer ids from the report):
- {"action":"build_field","patch_id":N}      claim a discovered patch: places drills,
                                              lays one-way track home, dispatches a train.
                                              Only patches with "affordable":true succeed.
- {"action":"add_train","field_id":N}         add a train to a field whose buffer is full.
- {"action":"abandon_field","field_id":N}      retire a field whose patch is depleted
                                              (report shows "depleted":true); salvages its train.
- {"action":"build_furnace","count":N}        deploy furnaces from stock to smelt faster.
- {"action":"build_assembler","count":N}      deploy assemblers from stock to craft faster.
- {"action":"expand_drills","field_id":N,"count":N}  add drills to a field.
- {"action":"research"}                        research the next tech level (report shows
                                              research.next with name/desc/affordable).
                                              Techs permanently boost drills, trains, smelting, etc.
- {"action":"wait","reason":"..."}            do nothing this turn.

Priorities: abandon ONLY fields with "depleted":true (never scrap a productive field)
to recover its train; never run out of coal (it fuels trains) - claim a coal patch if
the NO_COAL_FIELD or LOW_COAL flag is set; secure iron early; expand to affordable
patches; research the next tech when affordable (it compounds); and scale production.
Keep 1-3 actions per turn. Output JSON only."""


class Director:
    def __init__(self, sim, config):
        self.sim = sim
        self.config = config
        self.use_llm = bool(config.llm.enabled)
        self.client = (LLMClient(url=config.llm.url, model=config.llm.model,
                                 timeout=config.llm.timeout_seconds)
                       if self.use_llm else None)
        self.interval = config.llm.decision_interval_seconds or 6.0
        self._busy = False
        self._lock = threading.Lock()
        self._result = None
        self._gen = 0                  # bumped on reset() to discard stale workers
        self._next_time = 2.0          # first decision shortly after start
        self.online = self.use_llm     # is the LLM currently responding?
        self.source = "llm" if self.use_llm else "auto"
        self.decisions = 0
        self.last_report: dict | None = None
        self.last_reasoning = "Booting director..."
        # reconnect probe state
        self.retry_interval = RETRY_SECONDS
        self._probe_busy = False
        self._probe_lock = threading.Lock()
        self._probe_result: bool | None = None
        self._next_probe = 0.0         # monotonic clock

    # ---- main-thread driver ----------------------------------------------
    def update(self) -> None:
        self._apply_ready()
        self._check_reconnect()
        if not self._busy and self.sim.time >= self._next_time:
            self._start()

    def force_decision(self) -> None:
        if not self._busy:
            self._next_time = self.sim.time

    def reset(self) -> None:
        """Drop any in-flight/queued decision (e.g. after loading a save)."""
        with self._lock:
            self._result = None
        self._gen += 1
        self._busy = False
        self._next_time = self.sim.time + 0.5

    # ---- decision cycle ---------------------------------------------------
    def _start(self) -> None:
        report = build_report(self.sim)
        self.last_report = report
        self._next_time = self.sim.time + self.interval
        # Use the LLM only when enabled AND currently online (and not the very
        # first move). Otherwise decide instantly with the internal heuristic so
        # the game never stalls waiting on a dead endpoint.
        if self.use_llm and self.online and self.decisions > 0:
            self._busy = True
            threading.Thread(target=self._worker, args=(report, self._gen), daemon=True).start()
        else:
            self._deliver(report, fallback.decide(self.sim, report), "auto")

    def _worker(self, report: dict, gen: int) -> None:
        # Only the network call runs here; sim is NOT touched off the main thread.
        user = ("Game state report:\n" + json.dumps(report, separators=(",", ":"))
                + "\n\nReply with JSON only.")
        try:
            decision = self.client.chat_json(SYSTEM_PROMPT, user)
            if gen == self._gen:
                self._deliver(report, decision, "llm")
        except LLMError as e:
            if gen == self._gen:
                self._deliver(report, None, "llm_failed", note=str(e))

    def _deliver(self, report, decision, source, note: str | None = None) -> None:
        with self._lock:
            self._result = (report, decision, source, note)

    def _apply_ready(self) -> None:
        with self._lock:
            res = self._result
            self._result = None
        if not res:
            return
        report, decision, source, note = res
        self._busy = False
        self.decisions += 1

        if source == "llm":
            if not self.online:
                self._set_online()
        elif source == "llm_failed":
            self._set_offline(note or "gateway error")
            decision = fallback.decide(self.sim, report)
            source = "auto"

        self.source = source
        reasoning, actions, errors = validate(decision)
        self.last_reasoning = reasoning or "(no reasoning)"
        tag = "AI" if source == "llm" else "auto"
        self.sim.log(f"[{tag}] {self.last_reasoning}")
        for r in apply_actions(self.sim, actions):
            self.sim.log(f"    {r}")
        for e in errors[:3]:
            self.sim.log(f"    ! {e}")

    # ---- connectivity -----------------------------------------------------
    def _set_offline(self, note: str) -> None:
        if self.online:
            self.sim.log(f"[director] LLM unreachable ({_short(note)}). Switched to internal "
                         f"director; retrying every {int(self.retry_interval)}s.")
        self.online = False
        self._next_probe = time.monotonic() + self.retry_interval

    def _set_online(self) -> None:
        self.online = True
        self.sim.log("[director] LLM reconnected; resuming AI director.")

    def _check_reconnect(self) -> None:
        if not self.use_llm or self.online:
            return
        with self._probe_lock:
            result = self._probe_result
            self._probe_result = None
        if result is True:
            self._set_online()
            return
        if not self._probe_busy and time.monotonic() >= self._next_probe:
            self._probe_busy = True
            threading.Thread(target=self._probe, daemon=True).start()

    def _probe(self) -> None:
        ok = False
        try:
            ok = self.client.ping()
        except Exception:
            ok = False
        with self._probe_lock:
            self._probe_result = ok
        if not ok:
            self._next_probe = time.monotonic() + self.retry_interval
        self._probe_busy = False

    # ---- status for the HUD ----------------------------------------------
    @property
    def probing(self) -> bool:
        return self._probe_busy

    def seconds_to_retry(self) -> int:
        return max(0, int(round(self._next_probe - time.monotonic())))

    def status_text(self) -> str:
        if not self.use_llm:
            return "Director: AUTO"
        if self.online:
            return "Director: LLM"
        if self._probe_busy:
            return "Director: AUTO (LLM reconnecting…)"
        return f"Director: AUTO (LLM retry {self.seconds_to_retry()}s)"


def _short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"
