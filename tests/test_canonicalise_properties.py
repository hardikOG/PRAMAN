"""Property-based tests for `canonicalise.py` — the foundation everything
else in the ledger (hashing, signing, verification) is built on. Generates
random JSON-like structures (including Unicode, emoji, deep nesting, and
numeric edge cases) rather than relying only on hand-picked examples, since
this is exactly the kind of pure, cheap-to-fuzz function where a human is
unlikely to think of the input that breaks it.
"""

from __future__ import annotations

import json
import math

from apps.api.ledger.canonicalise import canonicalise
from hypothesis import given, settings
from hypothesis import strategies as st

# Deliberately finite, JSON-safe floats only — canonicalise() itself raises
# ValueError for NaN/Infinity (tested separately, not fuzzed), since JSON
# cannot represent them at all.
_finite_floats = st.floats(allow_nan=False, allow_infinity=False, width=64)

_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    _finite_floats,
    st.text(max_size=40),  # includes Unicode, emoji, control chars by default
)

_json_value = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=25,
)


@given(_json_value)
@settings(max_examples=300)
def test_canonicalise_is_deterministic(value: object) -> None:
    """The same value canonicalises to the same bytes every time — no
    dependence on hash-randomization, dict iteration order, or anything else
    not part of the value itself."""
    assert canonicalise(value) == canonicalise(value)  # type: ignore[arg-type]


@given(st.dictionaries(st.text(max_size=20), _json_scalars, min_size=1, max_size=8))
@settings(max_examples=300)
def test_canonicalise_is_independent_of_key_insertion_order(d: dict) -> None:
    """A dict and the same dict rebuilt with its keys inserted in reverse
    order must canonicalise identically — this is the entire point of
    canonicalisation existing instead of `json.dumps(sort_keys=True)` being
    called ad hoc in three places with no guarantee they agree."""
    reversed_d = {k: d[k] for k in reversed(list(d.keys()))}
    assert canonicalise(d) == canonicalise(reversed_d)


@given(_json_value)
@settings(max_examples=300)
def test_canonicalise_output_round_trips_through_json_loads(value: object) -> None:
    """Whatever bytes canonicalise() produces must themselves be valid JSON
    — a hash committing to unparseable bytes would be useless as evidence
    handed to a third party (an issuer, an auditor) who needs to read it
    back, not just trust the hash blindly."""
    raw = canonicalise(value)
    json.loads(raw.decode("utf-8"))  # must not raise


@given(st.integers(min_value=-1_000_000, max_value=1_000_000))
@settings(max_examples=100)
def test_whole_number_float_and_equivalent_int_canonicalise_identically(n: int) -> None:
    """1.0 and 1 are the same logical JSON number under JCS/ECMA-262
    Number::toString rules — if a payload happened to carry a float where
    another equally-valid serialization path produced an int for the exact
    same value (e.g. a confidence score that's exactly 1.0), the hash must
    not silently differ based on which Python type it happened to be."""
    assert canonicalise(float(n)) == canonicalise(n)


def test_nan_and_infinity_are_rejected_not_silently_miscanonicalised() -> None:
    """JSON cannot represent NaN/Infinity at all; canonicalise() must raise
    rather than emit something that looks plausible but isn't valid JSON
    (Python's `repr(float("nan"))` is `'nan'`, which is not a JSON token)."""
    import pytest

    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonicalise(bad)


@given(st.lists(_json_scalars, min_size=2, max_size=6, unique_by=lambda x: repr(x)))
@settings(max_examples=200)
def test_list_order_is_significant_unlike_dict_key_order(items: list) -> None:
    """Unlike dict keys, JSON array order is part of the value's identity —
    canonicalise() must not reorder list elements the way it reorders dict
    keys, since ProofBundlePayload.findings' order (for example) can carry
    meaning and reordering it should not be a no-op for hashing purposes."""
    reversed_items = list(reversed(items))
    if items != reversed_items:
        assert canonicalise(items) != canonicalise(reversed_items)
