"""S2 — intent/cart faithfulness. The core of PRAMAN: does the cart actually
satisfy what the human asked for, constraint by constraint, not just "is it
under budget."

Every constraint is checked against one identified *target item* — the cart
item the mandate's intent is actually about — rather than the cart as a
whole, which is what lets a strip-worthy add-on (a sock pack riding along
with a shoe purchase) be told apart from the shoe itself. Deterministic
constraint types (price/category/quantity/merchant/time-window) are checked
by a plain rule; the rest go to the LLM through the injection-hardened
prompt in `prompts/faithfulness.py`. `UNDETERMINED` is never silently
upgraded to `SATISFIED` — a low-confidence "yes" from the model is treated
exactly like "I don't know."
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from apps.api.gateway.prompts.faithfulness import SYSTEM_PROMPT, build_user_prompt
from apps.api.llm_client import LLMClient, LLMError, LLMResponseError
from apps.api.models.schemas import (
    Adjudicator,
    Cart,
    CartItem,
    Constraint,
    ConstraintType,
    Finding,
    Verdict,
)

_LLM_ADJUDICATED_TYPES = frozenset(
    {ConstraintType.ATTRIBUTE, ConstraintType.MUST_HAVE, ConstraintType.MUST_NOT_HAVE}
)


@dataclass(frozen=True)
class FaithfulnessResult:
    """S2's verdict: one `Finding` per constraint, the cart items identified
    as unrequested (candidates for strip/step-up in Phase 6's policy), and
    latency."""

    findings: list[Finding]
    unrequested_items: list[CartItem]
    latency_ms: float


def identify_target_item(cart: Cart, constraints: list[Constraint]) -> CartItem | None:
    """Identify which single cart item the mandate's constraints describe.

    An item is a candidate only if it has *every* attribute field any
    ATTRIBUTE constraint references (a sock pack with no "size" attribute
    is never a candidate for a "size" constraint — this is what keeps an
    add-on from being mistaken for the requested product). Ties are then
    broken by CATEGORY constraint match.

    Outputs: the single identified item, or `None` if the cart is
        ambiguous (zero or multiple equally-plausible candidates) — callers
        must treat that as "cannot determine", not "pick the first one".
    Complexity: O(items × constraints).
    """
    attribute_fields = {c.field for c in constraints if c.type == ConstraintType.ATTRIBUTE}
    candidates = [item for item in cart.items if attribute_fields.issubset(item.attributes.keys())]

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) <= 1:
        return None

    category_constraints = [c for c in constraints if c.type == ConstraintType.CATEGORY]
    if category_constraints:
        category_value = category_constraints[0].value
        narrowed = [
            item for item in candidates if item.attributes.get("category") == category_value
        ]
        if len(narrowed) == 1:
            return narrowed[0]

    return None


def _evaluate_rule_constraint(
    constraint: Constraint, cart: Cart, target_item: CartItem | None
) -> Finding:
    """Deterministic adjudication for MAX_PRICE, CATEGORY, QUANTITY,
    MERCHANT, TIME_WINDOW — a plain comparison, never an LLM call."""

    def satisfied(evidence: str, confidence: float = 1.0) -> Finding:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.SATISFIED,
            evidence=evidence,
            confidence=confidence,
            adjudicator=Adjudicator.RULE,
        )

    def violated(evidence: str, confidence: float = 1.0) -> Finding:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.VIOLATED,
            evidence=evidence,
            confidence=confidence,
            adjudicator=Adjudicator.RULE,
        )

    def undetermined(evidence: str) -> Finding:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.UNDETERMINED,
            evidence=evidence,
            confidence=0.0,
            adjudicator=Adjudicator.RULE,
        )

    if constraint.type == ConstraintType.MERCHANT:
        if cart.merchant_id == constraint.value:
            return satisfied(f"cart merchant '{cart.merchant_id}' matches")
        return violated(f"cart merchant '{cart.merchant_id}' != '{constraint.value}'")

    if constraint.type == ConstraintType.MAX_PRICE:
        try:
            cap_paise = int(constraint.value)
        except ValueError:
            return undetermined(f"could not parse MAX_PRICE value {constraint.value!r} as paise")
        amount = target_item.line_total_paise if target_item else cart.total_paise
        scope = f"item '{target_item.name}'" if target_item else "cart total"
        if amount <= cap_paise:
            return satisfied(f"{scope} {amount} paise <= cap {cap_paise} paise")
        return violated(f"{scope} {amount} paise > cap {cap_paise} paise")

    if constraint.type == ConstraintType.QUANTITY:
        try:
            expected_qty = int(constraint.value)
        except ValueError:
            return undetermined(f"could not parse QUANTITY value {constraint.value!r}")
        actual_qty = target_item.qty if target_item else sum(i.qty for i in cart.items)
        if actual_qty == expected_qty:
            return satisfied(f"quantity {actual_qty} matches")
        return violated(f"quantity {actual_qty} != expected {expected_qty}")

    if constraint.type == ConstraintType.CATEGORY:
        items_to_check = [target_item] if target_item else cart.items
        for item in items_to_check:
            if item is not None and item.attributes.get("category") == constraint.value:
                return satisfied(f"item '{item.name}' category matches '{constraint.value}'")
        # Categories aren't stored on CartItem directly in the fixed schema —
        # this checks the attributes bag, which the storefront populates
        # with a "category" key when building a quote (see quotes.py).
        return violated(f"no cart item has category '{constraint.value}'")

    if constraint.type == ConstraintType.TIME_WINDOW:
        # Cart (fixed schema, §6) carries no fulfilment timestamp to check a
        # deadline against — reporting UNDETERMINED here is the honest
        # answer, not a fabricated pass.
        return undetermined("cart has no fulfilment timestamp to check a time window against")

    return undetermined(f"unhandled deterministic constraint type: {constraint.type}")


def _evaluate_llm_constraint(
    constraint: Constraint,
    target_item: CartItem | None,
    llm_client: LLMClient,
    *,
    min_confidence: float,
) -> Finding:
    """LLM adjudication for ATTRIBUTE, MUST_HAVE, MUST_NOT_HAVE.

    A SATISFIED verdict below `min_confidence` is downgraded to
    UNDETERMINED — see module docstring.
    """
    if target_item is None:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.UNDETERMINED,
            evidence="cart is ambiguous — could not identify which item this constraint applies to",
            confidence=0.0,
            adjudicator=Adjudicator.LLM,
        )

    try:
        response = llm_client.complete_json(
            system=SYSTEM_PROMPT, user=build_user_prompt(constraint, target_item)
        )
        verdict = Verdict(response["verdict"])
        confidence = float(response["confidence"])
        evidence = str(response["evidence"])
    except (LLMError, LLMResponseError, KeyError, ValueError) as exc:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.UNDETERMINED,
            evidence=f"LLM adjudication failed: {exc}",
            confidence=0.0,
            adjudicator=Adjudicator.LLM,
        )

    if verdict == Verdict.SATISFIED and confidence < min_confidence:
        return Finding(
            constraint_id=constraint.id,
            verdict=Verdict.UNDETERMINED,
            evidence=f"low-confidence SATISFIED ({confidence:.2f}) downgraded: {evidence}",
            confidence=confidence,
            adjudicator=Adjudicator.LLM,
        )

    return Finding(
        constraint_id=constraint.id,
        verdict=verdict,
        evidence=evidence,
        confidence=confidence,
        adjudicator=Adjudicator.LLM,
    )


def detect_unrequested_items(cart: Cart, target_item: CartItem | None) -> list[CartItem]:
    """Every cart item other than the identified target item.

    Outputs: an empty list if the cart is ambiguous (`target_item is None`)
        — flagging items as unrequested when we couldn't even identify the
        requested one would be a guess, not a finding.
    """
    if target_item is None:
        return []
    return [item for item in cart.items if item.sku != target_item.sku]


def evaluate_faithfulness(
    cart: Cart,
    constraints: list[Constraint],
    llm_client: LLMClient,
    *,
    min_confidence: float,
) -> FaithfulnessResult:
    """Run every constraint's adjudication and detect unrequested items.

    Complexity: O(1) rule evaluation per deterministic constraint, plus one
        LLM call per LLM-adjudicated constraint.
    """
    start = time.perf_counter()
    target_item = identify_target_item(cart, constraints)

    findings: list[Finding] = []
    for constraint in constraints:
        if constraint.type in _LLM_ADJUDICATED_TYPES:
            findings.append(
                _evaluate_llm_constraint(
                    constraint, target_item, llm_client, min_confidence=min_confidence
                )
            )
        else:
            findings.append(_evaluate_rule_constraint(constraint, cart, target_item))

    if target_item is None and len(cart.items) > 1:
        # Ambiguous *and* more than one line item: rule constraints above
        # fell back to cart-aggregate checks (total price, "any item
        # matches category") specifically because there's no single item to
        # check against — but that fallback is silent about every item
        # *other* than whichever one happened to satisfy it, and
        # `detect_unrequested_items` below correctly refuses to guess which
        # items are unrequested. Without this finding, a cart with no
        # ATTRIBUTE/MUST_HAVE/MUST_NOT_HAVE constraint at all (a perfectly
        # plausible intent like "running shoes under ₹4000", no size
        # mentioned) plus a second, entirely unrequested same-category item
        # would satisfy every rule check and flag nothing as unrequested —
        # a silent upsell S2 was specifically built to catch. Surfacing
        # UNDETERMINED here routes it to STEP_UP via S4's existing
        # precedence instead of silently ALLOW.
        findings.append(
            Finding(
                constraint_id="_cart_ambiguity",
                verdict=Verdict.UNDETERMINED,
                evidence=(
                    f"cart has {len(cart.items)} items and no constraint narrows down which "
                    "one the intent is about — cannot verify every item was requested"
                ),
                confidence=0.0,
                adjudicator=Adjudicator.RULE,
            )
        )

    unrequested = detect_unrequested_items(cart, target_item)
    return FaithfulnessResult(
        findings=findings,
        unrequested_items=unrequested,
        latency_ms=(time.perf_counter() - start) * 1000,
    )
