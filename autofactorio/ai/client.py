"""OpenAI-compatible LLM client (stdlib only).

Talks to the LAN "Golden Eye" gateway (or any OpenAI-compatible /v1/chat/completions
endpoint). Matches the SimCity_LLM game-AI setup: thinking disabled, replies forced
to JSON, defensive parsing so a chatty model never crashes the game.

Pure standard library (urllib + json) so the only third-party deps stay pygame + numpy.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(Exception):
    """Raised when the gateway is unreachable, times out, or returns junk.

    The bridge catches this and falls back to the heuristic director, exactly
    like SimCity_LLM's `--fallback` path.
    """


@dataclass
class LLMClient:
    url: str = "http://192.168.15.3:21345"
    model: str = "qwen3:4b"
    timeout: float = 60.0
    temperature: float = 0.3
    max_tokens: int = 1024

    def chat_json(self, system: str, user: str) -> dict:
        """Send one decision turn and return the parsed JSON object.

        Raises LLMError on any transport/parse failure so callers can fall back.
        """
        raw = self.chat(system, user)
        obj = _extract_json_object(raw)
        if obj is None:
            raise LLMError(f"model did not return a JSON object: {raw[:200]!r}")
        return obj

    def chat(self, system: str, user: str) -> str:
        """Return the raw assistant text for a system+user exchange."""
        endpoint = self.url.rstrip("/") + "/v1/chat/completions"
        # `/no_think` disables qwen3's chain-of-thought via the Ollama-backed
        # gateway; the JSON instruction lives in the system prompt itself.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system.rstrip() + "\n/no_think"},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            # Honored by most OpenAI-compatible servers; harmless if ignored
            # because the prompt also demands JSON and parsing is defensive.
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer local",  # gateway ignores; some stacks require a header
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:  # 4xx/5xx
            detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
            raise LLMError(f"HTTP {e.code} from gateway: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f"cannot reach gateway at {endpoint}: {e}") from e

        try:
            obj = json.loads(body)
            return obj["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected gateway response shape: {body[:200]!r}") from e

    def ping(self) -> bool:
        """Best-effort reachability check used at startup to pick LLM vs fallback."""
        try:
            self.chat("You are a healthcheck.", "Reply with {\"ok\":true} only.")
            return True
        except LLMError:
            return False


def _extract_json_object(text: str) -> dict | None:
    """Pull the first balanced top-level JSON object out of model text.

    Tolerates ```json fences, leading prose, and trailing chatter. Returns the
    parsed dict, or None if nothing valid is found.
    """
    if not text:
        return None
    s = text.strip()
    # Fast path: the whole thing is JSON.
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    # Scan for a balanced { ... } that parses, respecting strings/escapes.
    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = s[start : i + 1]
                        try:
                            v = json.loads(candidate)
                            if isinstance(v, dict):
                                return v
                        except json.JSONDecodeError:
                            break  # malformed; advance to next '{'
        start = s.find("{", start + 1)
    return None
