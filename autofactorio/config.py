"""Runtime configuration: LLM endpoint, display, world seed.

Defaults match the SimCity_LLM game-AI setup (Golden Eye gateway). A `config.json`
next to the repo root (gitignored) can override any field; env vars win over that.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict


def _env(key: str, default):
    v = os.environ.get(key)
    if v is None:
        return default
    if isinstance(default, bool):
        return v.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(v)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(v)
        except ValueError:
            return default
    return v


@dataclass
class LLMConfig:
    url: str = "http://192.168.15.3:21345"
    model: str = "qwen3:4b"
    enabled: bool = True
    timeout_seconds: float = 60.0
    decision_interval_seconds: float = 4.0


@dataclass
class DisplayConfig:
    width: int = 1600
    height: int = 900
    fps: int = 60
    fullscreen: bool = False


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    seed: int = 1337

    # ---- loading ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        cfg = cls()
        data = {}
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

        llm = data.get("llm", {})
        cfg.llm = LLMConfig(
            url=_env("AUTOFACTORIO_LLM_URL", llm.get("url", cfg.llm.url)),
            model=_env("AUTOFACTORIO_MODEL", llm.get("model", cfg.llm.model)),
            enabled=_env("AUTOFACTORIO_LLM_ENABLED", llm.get("enabled", cfg.llm.enabled)),
            timeout_seconds=float(llm.get("timeout_seconds", cfg.llm.timeout_seconds)),
            decision_interval_seconds=float(llm.get("decision_interval_seconds", cfg.llm.decision_interval_seconds)),
        )

        disp = data.get("display", {})
        cfg.display = DisplayConfig(
            width=int(disp.get("width", cfg.display.width)),
            height=int(disp.get("height", cfg.display.height)),
            fps=int(disp.get("fps", cfg.display.fps)),
            fullscreen=bool(disp.get("fullscreen", cfg.display.fullscreen)),
        )

        world = data.get("world", {})
        cfg.seed = int(_env("AUTOFACTORIO_SEED", world.get("seed", cfg.seed)))
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)
