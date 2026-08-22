"""Decompose a mandate's natural-language intent into typed constraints,
once, at issue time (PRAMAN_BUILD.md §2, §3) — never re-derived at checkout.

Which constraint *types* are checked deterministically vs. routed to LLM
adjudication at checkout (Phase 5) is a fixed property of the type itself,
not something the extraction call decides per-instance: price, category,
quantity, merchant, and time-window comparisons are plain rules; attribute
matching and must-(not-)have checks are inherently fuzzy semantic judgments.
"""

from __future__ import annotations

import uuid

from apps.api.llm_client import LLMClient, LLMResponseError
from apps.api.models.schemas import Constraint, ConstraintType

_DETERMINISTIC_TYPES = frozenset(
    {
        ConstraintType.MAX_PRICE,
        ConstraintType.CATEGORY,
        ConstraintType.QUANTITY,
        ConstraintType.MERCHANT,
        ConstraintType.TIME_WINDOW,
    }
)
"""Constraint types S2 always checks with a plain rule (never an LLM call) —
see PRAMAN_BUILD.md §3: "Price, quantity, merchant, category are never left
to an LLM." Time-window comparisons are the same kind of plain comparison."""


def is_deterministic_type(constraint_type: ConstraintType) -> bool:
    """Whether `constraint_type` is always rule-checked (not LLM-adjudicated).

    This is a fixed mapping, not a per-instance LLM judgment — determinism is
    a property of the constraint kind, not something worth asking a
    probabilistic model to self-report.
    """
    return constraint_type in _DETERMINISTIC_TYPES


_SYSTEM_PROMPT = """You decompose a human's shopping instruction into a list of typed, \
checkable constraints for an AI purchasing agent to satisfy.

Return ONLY a JSON object: {"constraints": [...]}. Each constraint object has:
  "type": one of MAX_PRICE, CATEGORY, ATTRIBUTE, QUANTITY, MERCHANT, MUST_HAVE, \
MUST_NOT_HAVE, TIME_WINDOW
  "field": the property being constrained (e.g. "price", "size", "colour")
  "operator": a short comparison operator, e.g. "<=", "==", "!=", "in"
  "value": the constraint's value as a string (prices in integer paise)
  "source_span": the exact substring of the instruction this constraint came from

Rules:
- Extract every distinct constraint; do not merge unrelated ones.
- A price limit like "under ₹4000" is MAX_PRICE, value "400000" (paise), operator "<=".
- A product category like "running shoes" is CATEGORY.
- A size, colour, or spec preference is ATTRIBUTE.
- An explicit exclusion ("not white", "no leather") is MUST_NOT_HAVE.
- An explicit requirement beyond category ("must have free cancellation") is MUST_HAVE.
- A quantity ("two pairs") is QUANTITY; if unstated, do not emit one.
- A merchant name is MERCHANT; if unstated, do not emit one.
- A deadline or date range is TIME_WINDOW.
Do not invent constraints the instruction does not state."""


def extract_constraints(intent_text: str, llm_client: LLMClient) -> list[Constraint]:
    """Extract the typed constraint set for `intent_text`.

    Inputs: `intent_text` — the human's raw instruction; `llm_client` — the
        injected LLM dependency (real or a test double).
    Outputs: a list of `Constraint`, each with a freshly generated `id` and
        `is_deterministic` set from the type, never from the model.
    Complexity: O(1) LLM call plus O(n) parsing in the number of constraints
        returned.
    Failure cases: propagates `LLMError`/`LLMResponseError` from the client;
        raises `LLMResponseError` if the response is missing the expected
        `constraints` list or a constraint has an unrecognised `type`.
    """
    user_prompt = f'Decompose this instruction:\n"""\n{intent_text}\n"""'
    response = llm_client.complete_json(system=_SYSTEM_PROMPT, user=user_prompt)

    raw_constraints = response.get("constraints")
    if not isinstance(raw_constraints, list):
        raise LLMResponseError(f"expected a 'constraints' list, got: {response!r}")

    constraints: list[Constraint] = []
    for raw in raw_constraints:
        try:
            constraint_type = ConstraintType(raw["type"])
        except (KeyError, ValueError) as exc:
            raise LLMResponseError(f"unrecognised constraint in response: {raw!r}") from exc

        constraints.append(
            Constraint(
                id=str(uuid.uuid4()),
                type=constraint_type,
                field=str(raw["field"]),
                operator=str(raw["operator"]),
                value=str(raw["value"]),
                is_deterministic=is_deterministic_type(constraint_type),
                source_span=str(raw.get("source_span", "")),
            )
        )
    return constraints
