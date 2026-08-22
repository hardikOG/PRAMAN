"""JSON Canonicalization (RFC 8785 / JCS-style) for ledger payloads.

Exists so hashing and signing operate on one unambiguous byte representation
of a JSON value, regardless of the key insertion order the caller happened to
build it in. Every place that needs "the canonical bytes of this payload"
(chain.py's hashing, bundle.py's signing, verify.py's independent check)
calls this module instead of hand-rolling `sort_keys=True` in three places.

This targets JCS's ordering and separator rules (recursive key sort, no
insignificant whitespace) and ECMA-262's `Number::toString` formatting for
floats, since our payloads carry a handful of confidence/score floats
alongside integer paise amounts. It does not implement every RFC 8785 corner
case (e.g. non-finite numbers, which JSON itself cannot represent) — those
inputs are rejected outright rather than silently miscanonicalised.
"""

from __future__ import annotations

import math
from typing import Any

JsonValue = None | bool | int | float | str | list[Any] | dict[str, Any]


def canonicalise(value: JsonValue) -> bytes:
    """Serialize `value` to its canonical JSON bytes.

    Inputs: any JSON-compatible Python value (the output of
        `pydantic.BaseModel.model_dump(mode="json")` satisfies this).
    Outputs: UTF-8 bytes such that two structurally-equal values (including
        dicts with differently-ordered keys) always produce identical bytes.
    Complexity: O(n) in the total number of scalar values, dict keys sorted
        with the standard library's Timsort (O(k log k) per object).
    Failure cases: raises `TypeError` for values outside `JsonValue` (e.g. a
        set, a datetime — callers must pre-serialize those to str/int first,
        which Pydantic's `mode="json"` dump already does), and `ValueError`
        for non-finite floats (NaN/Infinity), which JSON cannot represent.
    """
    return _encode(value).encode("utf-8")


def _encode(value: JsonValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _encode_float(value)
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0])
        return (
            "{"
            + ",".join(f"{_encode_string(k)}:{_encode(v)}" for k, v in items)
            + "}"
        )
    raise TypeError(f"cannot canonicalise value of type {type(value).__name__}")


def _encode_string(s: str) -> str:
    # json.dumps already produces RFC 8259-compliant escaping; ensure_ascii is
    # off so non-ASCII (e.g. प्रमाण in intent text) round-trips as UTF-8 rather
    # than \uXXXX escapes, which would otherwise still canonicalise
    # consistently but needlessly bloat every bundle.
    import json

    return json.dumps(s, ensure_ascii=False)


def _encode_float(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"cannot canonicalise non-finite float: {f!r}")
    if f == int(f) and abs(f) < 1e15:
        # JCS/ECMA-262 renders whole-numbered floats without a trailing ".0"
        # (e.g. 1.0 -> "1"), matching how a JS `JSON.stringify` peer would
        # serialize the same logical value.
        return str(int(f))
    return repr(f)
