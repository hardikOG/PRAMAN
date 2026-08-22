"""Phase 1 gate: canonicalisation is stable across dict-key reordering, over
1,000 random payloads (Hypothesis), and rejects non-JSON-compatible input.
"""

from __future__ import annotations

import json
import random

import pytest
from apps.api.ledger.canonicalise import canonicalise
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=20),
)


def _json_values() -> st.SearchStrategy:
    return st.recursive(
        _json_scalars,
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(st.text(max_size=10), children, max_size=5),
        ),
        max_leaves=20,
    )


def _reorder_keys(value: object) -> object:
    """Return a structurally-equal value with every dict's key insertion
    order shuffled, recursively."""
    if isinstance(value, dict):
        items = [(k, _reorder_keys(v)) for k, v in value.items()]
        random.shuffle(items)
        return dict(items)
    if isinstance(value, list):
        return [_reorder_keys(item) for item in value]
    return value


@given(value=_json_values())
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
def test_canonicalise_stable_across_key_reordering(value: object) -> None:
    """1,000 random JSON-like payloads: reordering dict keys must not change
    the canonical bytes (the Phase 1 gate's core property)."""
    reordered = _reorder_keys(value)
    assert canonicalise(value) == canonicalise(reordered)


@given(value=_json_values())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_canonicalise_is_deterministic(value: object) -> None:
    """Canonicalising the same value twice gives byte-identical output."""
    assert canonicalise(value) == canonicalise(value)


def test_canonicalise_matches_expected_bytes_for_a_known_payload() -> None:
    """A concrete example, independent of the property tests, pinning the
    exact wire format (sorted keys, compact separators)."""
    payload = {"b": 1, "a": [1, 2, {"z": True, "y": None}]}
    assert canonicalise(payload) == b'{"a":[1,2,{"y":null,"z":true}],"b":1}'


def test_canonicalise_renders_whole_number_floats_without_trailing_zero() -> None:
    assert canonicalise({"x": 1.0}) == b'{"x":1}'


def test_canonicalise_rejects_nan_and_infinity() -> None:
    with pytest.raises(ValueError):
        canonicalise({"x": float("nan")})
    with pytest.raises(ValueError):
        canonicalise({"x": float("inf")})


def test_canonicalise_rejects_non_json_types() -> None:
    with pytest.raises(TypeError):
        canonicalise({"x", "not", "json", "serializable", "set"})  # type: ignore[arg-type]


def test_canonicalise_output_is_valid_json() -> None:
    payload = {"nested": {"list": [1, "two", 3.5, None, False]}}
    parsed = json.loads(canonicalise(payload))
    assert parsed == payload
