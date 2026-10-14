"""Plain-language explanations of gateway decisions.

The gateway's own vocabulary — `constraint_violated:112b34f2-…`,
`unrequested_items:TOTE-20`, a token hash — is exact and auditable, and
meaningless to the two people who actually need to act on a decision: the
shopper deciding whether to approve a purchase, and the merchant's ops person
reading a dispute. This module is the one place that turns a decision's
`reason_code` and findings into sentences, so the API, the shopper screen, and
the ledger all say the same thing instead of each inventing their own wording.

Pure functions only: no I/O, nothing to mock, trivially testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from apps.api.models.schemas import Cart, Finding, Verdict

_UNREQUESTED_PREFIX = "unrequested_items:"

_S1_REASONS = {
    "s1_invalid_signature": "The authorization for this agent could not be verified.",
    "s1_revoked": "The authorization for this agent has been revoked.",
    "s1_expired": "The authorization for this agent has expired.",
    "s1_merchant_not_allowlisted": "This merchant isn't one the shopper authorized.",
    "s1_per_txn_cap_exceeded": "This order is larger than the per-purchase limit the shopper set.",
    "s1_budget_exceeded": "This order would go over the shopper's total budget.",
    "s1_replay_detected": "This exact cart was already submitted once — it can't be charged twice.",
    "s1_velocity_exceeded": "The agent is making purchases faster than the shopper allowed.",
}


def rupees(paise: int) -> str:
    """Format integer paise as a rupee string (₹3,499 or ₹999.50).

    Display only — money stays integer paise everywhere it is computed.
    """
    whole, remainder = divmod(paise, 100)
    return f"₹{whole:,}" if remainder == 0 else f"₹{whole:,}.{remainder:02d}"


def unrequested_skus_from_reason(reason_code: str) -> list[str]:
    """SKUs named in an `unrequested_items:SKU,SKU` reason code, else `[]`."""
    if not reason_code.startswith(_UNREQUESTED_PREFIX):
        return []
    return [sku for sku in reason_code[len(_UNREQUESTED_PREFIX) :].split(",") if sku]


def plain_reason(reason_code: str, findings: Sequence[Finding]) -> str:
    """One sentence a non-engineer can act on, for any decision's reason.

    Inputs: the decision's `reason_code` and its findings (a violated
        constraint's own `evidence` text is the most specific thing we have).
    Outputs: a sentence. Unknown codes fall back to a neutral phrasing rather
        than leaking the raw code at someone who can't use it.
    Complexity: O(findings).
    """
    if reason_code == "all_constraints_satisfied":
        return "Everything in the cart matches what was asked for."
    if reason_code.startswith("step_up_confirmed:"):
        return "A person reviewed and approved this purchase."
    if reason_code.startswith("step_up_declined:"):
        return "A person reviewed this purchase and declined it."
    if reason_code in _S1_REASONS:
        return _S1_REASONS[reason_code]
    if reason_code.startswith(_UNREQUESTED_PREFIX):
        skus = ", ".join(unrequested_skus_from_reason(reason_code))
        return f"The cart contains something that wasn't asked for ({skus})."
    if reason_code.startswith("constraint_violated:"):
        violated = [f for f in findings if f.verdict == Verdict.VIOLATED]
        if violated:
            return f"Doesn't match the request: {violated[0].evidence}."
        return "The cart doesn't match what was asked for."
    if reason_code.startswith("constraint_undetermined:"):
        return "We couldn't tell whether the cart matches what was asked for."
    if reason_code.startswith("behaviour_anomaly:"):
        return "The agent's activity looked unusual compared with normal buying."
    return "This purchase needs a closer look."


@dataclass(frozen=True)
class StepUpItemView:
    """One cart line as the shopper sees it."""

    sku: str
    name: str
    qty: int
    line_total_paise: int
    unrequested: bool


@dataclass(frozen=True)
class StepUpContext:
    """Everything the shopper's confirmation screen needs, and nothing more."""

    decision_id: str
    intent_text: str
    headline: str
    detail: str
    items: list[StepUpItemView]
    total_paise: int
    unrequested_paise: int
    unrequested_percent: int
    can_remove: bool
    expires_in_seconds: int


def build_step_up_context(
    *,
    decision_id: str,
    reason_code: str,
    cart: Cart,
    intent_text: str,
    expires_in_seconds: int,
) -> StepUpContext:
    """Turn a pending STEP_UP decision into the shopper's confirmation view.

    Inputs: the decision's id and reason code, the cart it was about, the
        shopper's own words (`intent_text`), and how long the link lives.
    Outputs: a `StepUpContext`. When the reason is an unrequested add-on,
        `can_remove` is true and the add-on lines are flagged; for any other
        reason there is nothing specific to remove, so only pay/cancel apply.
    Complexity: O(items).
    """
    unrequested_skus = set(unrequested_skus_from_reason(reason_code))
    items = [
        StepUpItemView(
            sku=item.sku,
            name=item.name,
            qty=item.qty,
            line_total_paise=item.line_total_paise,
            unrequested=item.sku in unrequested_skus,
        )
        for item in cart.items
    ]
    unrequested_paise = sum(i.line_total_paise for i in items if i.unrequested)
    percent = (
        (unrequested_paise * 100 + cart.total_paise // 2) // cart.total_paise
        if cart.total_paise
        else 0
    )

    if unrequested_skus:
        names = ", ".join(i.name for i in items if i.unrequested)
        headline = f"Your agent added {names} you didn't ask for"
        detail = (
            f"It adds {rupees(unrequested_paise)} — {percent}% of this "
            f"{rupees(cart.total_paise)} order. You asked for: “{intent_text}”."
        )
    elif reason_code.startswith("constraint_undetermined:"):
        headline = "We couldn't confirm this matches what you asked for"
        detail = f"You asked for: “{intent_text}”. Check the items below before paying."
    elif reason_code.startswith("behaviour_anomaly:"):
        headline = "Your agent's activity looked unusual"
        detail = f"It's buying faster or differently than usual. You asked for: “{intent_text}”."
    else:
        headline = "This purchase needs your OK"
        detail = f"You asked for: “{intent_text}”."

    return StepUpContext(
        decision_id=decision_id,
        intent_text=intent_text,
        headline=headline,
        detail=detail,
        items=items,
        total_paise=cart.total_paise,
        unrequested_paise=unrequested_paise,
        unrequested_percent=percent,
        can_remove=bool(unrequested_skus),
        expires_in_seconds=expires_in_seconds,
    )
