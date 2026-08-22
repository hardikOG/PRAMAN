"""Phase 2 gate: 'running shoes under ₹4000, size 9, not white' extracts
exactly four typed constraints with the correct `is_deterministic` flags.
"""

from __future__ import annotations

import pytest
from apps.api.llm_client import LLMResponseError
from apps.api.mandates.constraint_extraction import extract_constraints, is_deterministic_type
from apps.api.models.schemas import ConstraintType

from tests.fakes import FakeLLMClient

_GATE_INTENT = "running shoes under ₹4000, size 9, not white"

_GATE_LLM_RESPONSE = {
    "constraints": [
        {
            "type": "MAX_PRICE",
            "field": "price",
            "operator": "<=",
            "value": "400000",
            "source_span": "under ₹4000",
        },
        {
            "type": "CATEGORY",
            "field": "category",
            "operator": "==",
            "value": "footwear.running",
            "source_span": "running shoes",
        },
        {
            "type": "ATTRIBUTE",
            "field": "size",
            "operator": "==",
            "value": "9",
            "source_span": "size 9",
        },
        {
            "type": "MUST_NOT_HAVE",
            "field": "colour",
            "operator": "!=",
            "value": "white",
            "source_span": "not white",
        },
    ]
}


def test_gate_example_extracts_exactly_four_constraints_with_correct_determinism() -> None:
    llm_client = FakeLLMClient(_GATE_LLM_RESPONSE)
    constraints = extract_constraints(_GATE_INTENT, llm_client)

    assert len(constraints) == 4

    by_type = {c.type: c for c in constraints}
    assert by_type[ConstraintType.MAX_PRICE].is_deterministic is True
    assert by_type[ConstraintType.CATEGORY].is_deterministic is True
    assert by_type[ConstraintType.ATTRIBUTE].is_deterministic is False
    assert by_type[ConstraintType.MUST_NOT_HAVE].is_deterministic is False

    assert by_type[ConstraintType.MAX_PRICE].value == "400000"
    assert by_type[ConstraintType.ATTRIBUTE].value == "9"


@pytest.mark.parametrize(
    "constraint_type,expected",
    [
        (ConstraintType.MAX_PRICE, True),
        (ConstraintType.CATEGORY, True),
        (ConstraintType.QUANTITY, True),
        (ConstraintType.MERCHANT, True),
        (ConstraintType.TIME_WINDOW, True),
        (ConstraintType.ATTRIBUTE, False),
        (ConstraintType.MUST_HAVE, False),
        (ConstraintType.MUST_NOT_HAVE, False),
    ],
)
def test_is_deterministic_type_mapping(constraint_type: ConstraintType, expected: bool) -> None:
    assert is_deterministic_type(constraint_type) is expected


def test_each_extracted_constraint_gets_a_unique_id() -> None:
    llm_client = FakeLLMClient(_GATE_LLM_RESPONSE)
    constraints = extract_constraints(_GATE_INTENT, llm_client)
    assert len({c.id for c in constraints}) == len(constraints)


def test_missing_constraints_key_raises_llm_response_error() -> None:
    llm_client = FakeLLMClient({"oops": []})
    with pytest.raises(LLMResponseError):
        extract_constraints(_GATE_INTENT, llm_client)


def test_unrecognised_constraint_type_raises_llm_response_error() -> None:
    llm_client = FakeLLMClient(
        {"constraints": [{"type": "NOT_A_REAL_TYPE", "field": "x", "operator": "==", "value": "y"}]}
    )
    with pytest.raises(LLMResponseError):
        extract_constraints(_GATE_INTENT, llm_client)
