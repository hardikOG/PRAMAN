"""A general-purpose offline stand-in for S2's LLM adjudication, used by
the eval harness when no `ANTHROPIC_API_KEY` is configured.

This is deliberately NOT presented as a measurement of model accuracy: it
parses the structured `field`/`value`/`attributes` text straight out of
`build_user_prompt`'s rendered prompt (via regex + `ast.literal_eval`) and
does a plain string comparison — no language understanding at all. Every
report this produces says so explicitly. It exists so the harness's
mechanics (scenario generation, the pipeline, scoring, the ablation sweep,
report generation) can be proven correct and reproducible without an API
key; re-running with a real key exercises the exact same code path against
genuine model behaviour.
"""

from __future__ import annotations

import ast
import re

_FIELD_RE = re.compile(r"^\s*field:\s*(.+)$", re.MULTILINE)
_VALUE_RE = re.compile(r"^\s*value:\s*(.+)$", re.MULTILINE)
_TYPE_RE = re.compile(r"^\s*type:\s*(.+)$", re.MULTILINE)
_ATTRS_RE = re.compile(r"^attributes:\s*(\{.*\})\s*$", re.MULTILINE)


def _normalize(value: str) -> str:
    return value.strip().lower().removeprefix("uk")


def offline_faithfulness_response(system: str, user: str) -> dict:
    """Route a rendered S2 prompt to a structural, non-LLM verdict.

    Only ever called for `stage_faithfulness.py`'s LLM-adjudicated
    constraint types (ATTRIBUTE, MUST_HAVE, MUST_NOT_HAVE) — constraint
    extraction never reaches this module in the eval harness, since
    scenarios specify their constraint set directly (see `agents/scenario.py`).
    """
    field_match = _FIELD_RE.search(user)
    value_match = _VALUE_RE.search(user)
    type_match = _TYPE_RE.search(user)
    attrs_match = _ATTRS_RE.search(user)

    if not (field_match and value_match and type_match and attrs_match):
        return {
            "verdict": "UNDETERMINED",
            "evidence": "could not parse prompt structure",
            "confidence": 0.0,
        }

    field = field_match.group(1).strip()
    expected_value = _normalize(value_match.group(1))
    constraint_type = type_match.group(1).strip()
    try:
        attributes = ast.literal_eval(attrs_match.group(1))
    except (ValueError, SyntaxError):
        return {
            "verdict": "UNDETERMINED",
            "evidence": "could not parse item attributes",
            "confidence": 0.0,
        }

    actual_value = attributes.get(field)

    if constraint_type == "MUST_NOT_HAVE":
        if actual_value is None:
            return {
                "verdict": "SATISFIED",
                "evidence": f"item has no '{field}'",
                "confidence": 0.85,
            }
        matches = _normalize(actual_value) == expected_value
        return (
            {"verdict": "VIOLATED", "evidence": f"'{field}' is '{actual_value}'", "confidence": 0.9}
            if matches
            else {
                "verdict": "SATISFIED",
                "evidence": f"'{field}' is '{actual_value}', not excluded",
                "confidence": 0.85,
            }
        )

    # ATTRIBUTE / MUST_HAVE
    if actual_value is None:
        return {"verdict": "UNDETERMINED", "evidence": f"item has no '{field}'", "confidence": 0.0}
    matches = _normalize(actual_value) == expected_value
    return (
        {
            "verdict": "SATISFIED",
            "evidence": f"'{field}'='{actual_value}' matches",
            "confidence": 0.88,
        }
        if matches
        else {
            "verdict": "VIOLATED",
            "evidence": f"'{field}'='{actual_value}' != '{expected_value}'",
            "confidence": 0.88,
        }
    )
