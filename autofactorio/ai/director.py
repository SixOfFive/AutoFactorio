"""The director: drives expansion decisions, LLM-first with heuristic fallback.

Threading model mirrors SimCity_LLM: the slow LLM call runs on a daemon worker
thread so the UI never stalls; the resulting actions are applied on the main
thread during update(). If the gateway errors, this turn falls back to the
heuristic director and we keep retrying the LLM on later turns.
"""

from __future__ import annotations

import json
import threading

from .client import LLMClient, LLMError
from .report import build_report
from .schema import validate
from .apply import apply_actions
from . import fallback

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
- {"action":"wait","reason":"..."}            do nothing this turn.

Priorities: abandon any field with "depleted":true to recover its train; never run
out of coal (it fuels trains) - claim a coal patch if the NO_COAL_FIELD or LOW_COAL
flag is set; secure iron early; then expand to affordable patches and scale
production. Keep 1-3 actions per turn. Output JSON only."""


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
        self._next_time = 2.0          # first decision shortly after start
        self.online = self.use_llm     # display: is the LLM responding?
        self.source = "llm" if self.use_llm else "auto"
        self.decisions = 0
        self.last_report: dict | None = None
        self.last_reasoning = "Booting director..."

    # ---- main-thread driver ----------------------------------------------
    def update(self) -> None:
        self._apply_ready()
        if not self._busy and self.sim.time >= self._next_time:
            self._start()

    def force_decision(self) -> None:
        """Trigger a decision now (e.g. user keypress)."""
        if not self._busy:
            self._next_time = self.sim.time

    def _start(self) -> None:
        report = build_report(self.sim)
        self.last_report = report
        self._next_time = self.sim.time + self.interval
        # First move is always the instant heuristic so the base starts building
        # immediately instead of waiting on the LLM's first (slow) reply.
        if self.use_llm and self.decisions > 0:
            self._busy = True
            threading.Thread(target=self._worker, args=(report,), daemon=True).start()
        else:
            self._deliver(report, fallback.decide(self.sim, report), "auto")

    def _worker(self, report: dict) -> None:
        # Only the network call runs here; sim is NOT touched off the main thread.
        user = ("Game state report:\n" + json.dumps(report, separators=(",", ":"))
                + "\n\nReply with JSON only.")
        try:
            decision = self.client.chat_json(SYSTEM_PROMPT, user)
            self.online = True
            self._deliver(report, decision, "llm")
        except LLMError as e:
            self.online = False
            self._deliver(report, None, "llm_failed",
                          note=f"LLM unavailable ({e}); using heuristic director.")

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
        if note:
            self.sim.log(f"[director] {note}")
        if source == "llm_failed":            # run the heuristic on the main thread
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
