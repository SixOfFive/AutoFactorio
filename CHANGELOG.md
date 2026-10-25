# Changelog

## 2026-10-25

### Changed
- **The default LLM endpoint is now UltimateController (uC) at `http://192.168.15.3:11434`.**
  It was Golden Eye `192.168.15.3:21345`. Changed in `autofactorio/config.py`,
  `autofactorio/ai/client.py`, `config.example.json`, the README and `docs/ARCHITECTURE.md`.
  The client still appends `/v1/chat/completions` itself, and the model is still `qwen3:4b`,
  which uC routes by name.
  - Why: Golden Eye is retired, and every LLM caller moves to uC.
  - Verified: `LLMClient().chat_json(...)` returned `{'ok': True}` in 3.7 s once warm.
  - Caveat: the first request after `qwen3:4b` has been idle loads it cold on uC (it ran on
    `amdcomp-ollama`) and took about 62 s. That is just over the 60 s default timeout, so the
    first decision can fall back to the heuristic director. Later ones are fast.
  - Undo: `git revert` this commit, or set `AUTOFACTORIO_LLM_URL`.
