"""Action schema + validation for director decisions.

The director (LLM or fallback) returns a dict:
    {"reasoning": "...", "actions": [ {"action": "...", ...}, ... ]}
This module sanitizes that into a clean list of action dicts, dropping anything
malformed so a chatty/wrong model can never crash the apply step.
"""

from __future__ import annotations

# action -> {field: (type, required, default)}
_SPEC = {
    "build_field":     {"patch_id": (int, True, None), "tier": (str, False, None)},
    "add_train":       {"field_id": (int, True, None)},
    "abandon_field":   {"field_id": (int, True, None)},
    "build_assembler": {"count": (int, False, 1)},
    "build_furnace":   {"count": (int, False, 1)},
    "expand_drills":   {"field_id": (int, True, None), "count": (int, False, 2)},
    "research":        {},
    "wait":            {"reason": (str, False, "")},
}

VALID_ACTIONS = tuple(_SPEC.keys())


def _coerce(value, typ):
    try:
        if typ is int:
            return int(value)
        if typ is str:
            return str(value)
    except (TypeError, ValueError):
        return None
    return value


def validate(decision: dict) -> tuple[str, list[dict], list[str]]:
    """Return (reasoning, clean_actions, errors)."""
    errors: list[str] = []
    if not isinstance(decision, dict):
        return "", [], ["decision was not a JSON object"]

    reasoning = str(decision.get("reasoning", ""))[:400]

    raw = decision.get("actions", [])
    if isinstance(raw, dict):                 # tolerate a single action object
        raw = [raw]
    if not isinstance(raw, list):
        return reasoning, [], ["'actions' was not a list"]

    clean: list[dict] = []
    for i, a in enumerate(raw):
        if not isinstance(a, dict):
            errors.append(f"action[{i}] not an object")
            continue
        name = a.get("action") or a.get("type") or a.get("name")
        if name not in _SPEC:
            errors.append(f"action[{i}] unknown action {name!r}")
            continue
        spec = _SPEC[name]
        out = {"action": name}
        ok = True
        for field, (typ, required, default) in spec.items():
            if field in a and a[field] is not None:
                v = _coerce(a[field], typ)
                if v is None:
                    errors.append(f"action[{i}] bad {field}")
                    ok = False
                    break
                out[field] = v
            elif required:
                errors.append(f"action[{i}] missing {field}")
                ok = False
                break
            elif default is not None:
                out[field] = default
        if ok:
            clean.append(out)
    return reasoning, clean, errors
