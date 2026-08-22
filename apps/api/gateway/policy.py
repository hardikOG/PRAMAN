"""S4 — policy fusion. Combines S1 (mandate), S2 (faithfulness), and S3
(behaviour) into one three-state decision: ALLOW, STEP_UP, or BLOCK.

Precedence, most severe first: an S1 failure or any VIOLATED constraint is a
hard BLOCK — a forged mandate or a wrong-size shoe is never negotiable. Any
UNDETERMINED constraint, an unrequested item too large (or too policy-
disallowed) to auto-strip, or a behavioural anomaly all STEP_UP — uncertain,
not wrong, so the human gets a chance to confirm rather than losing the
sale outright. Only when every check clears does the cart ALLOW.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.gateway.stage_behaviour import BehaviourResult
from apps.api.gateway.stage_faithfulness import FaithfulnessResult
from apps.api.gateway.stage_mandate import MandateStageResult
from apps.api.models.schemas import DecisionOutcome, Verdict


@dataclass(frozen=True)
class PolicyResult:
    """S4's fused verdict: the three-state outcome, a reason code for the
    decision trace, and which SKUs (if any) were auto-stripped."""

    outcome: DecisionOutcome
    reason_code: str
    stripped_skus: list[str]


def fuse_decision(
    mandate_result: MandateStageResult,
    faithfulness_result: FaithfulnessResult,
    behaviour_result: BehaviourResult,
    *,
    auto_strip_unrequested: bool,
    auto_strip_max_fraction: float,
    cart_total_paise: int,
    behaviour_step_up_threshold: float,
) -> PolicyResult:
    """Fuse the three stages into one decision.

    Complexity: O(k) in the number of findings/unrequested items.
    """
    if not mandate_result.passed:
        return PolicyResult(DecisionOutcome.BLOCK, f"s1_{mandate_result.reason_code}", [])

    violated = [f for f in faithfulness_result.findings if f.verdict == Verdict.VIOLATED]
    if violated:
        ids = ",".join(f.constraint_id for f in violated)
        return PolicyResult(DecisionOutcome.BLOCK, f"constraint_violated:{ids}", [])

    undetermined = [f for f in faithfulness_result.findings if f.verdict == Verdict.UNDETERMINED]
    if undetermined:
        ids = ",".join(f.constraint_id for f in undetermined)
        return PolicyResult(DecisionOutcome.STEP_UP, f"constraint_undetermined:{ids}", [])

    stripped_skus: list[str] = []
    if faithfulness_result.unrequested_items:
        unrequested_value = sum(i.line_total_paise for i in faithfulness_result.unrequested_items)
        fraction = unrequested_value / cart_total_paise if cart_total_paise > 0 else 1.0
        if auto_strip_unrequested and fraction <= auto_strip_max_fraction:
            stripped_skus = [i.sku for i in faithfulness_result.unrequested_items]
        else:
            skus = ",".join(i.sku for i in faithfulness_result.unrequested_items)
            return PolicyResult(DecisionOutcome.STEP_UP, f"unrequested_items:{skus}", [])

    if behaviour_result.score >= behaviour_step_up_threshold:
        signals = ",".join(behaviour_result.signals)
        return PolicyResult(DecisionOutcome.STEP_UP, f"behaviour_anomaly:{signals}", stripped_skus)

    return PolicyResult(DecisionOutcome.ALLOW, "all_constraints_satisfied", stripped_skus)
