"""S4 policy fusion: precedence (BLOCK > STEP_UP > ALLOW), strip-vs-step-up
threshold logic, and reason codes.
"""

from __future__ import annotations

from apps.api.gateway.policy import fuse_decision
from apps.api.gateway.stage_behaviour import BehaviourResult
from apps.api.gateway.stage_faithfulness import FaithfulnessResult
from apps.api.gateway.stage_mandate import MandateStageResult
from apps.api.models.schemas import Adjudicator, CartItem, DecisionOutcome, Finding, Verdict

_PASS_S1 = MandateStageResult(passed=True, reason_code="ok", latency_ms=1.0)
_FAIL_S1 = MandateStageResult(passed=False, reason_code="revoked", latency_ms=1.0)
_QUIET_S3 = BehaviourResult(score=0.0, signals=[], latency_ms=1.0)
_ANOMALOUS_S3 = BehaviourResult(score=0.6, signals=["burst_request_rate"], latency_ms=1.0)


def _finding(verdict: Verdict, constraint_id: str = "c1") -> Finding:
    return Finding(
        constraint_id=constraint_id,
        verdict=verdict,
        evidence="x",
        confidence=0.9,
        adjudicator=Adjudicator.RULE,
    )


def _item(sku: str, price: int) -> CartItem:
    return CartItem(sku=sku, name=sku, description="", unit_price_paise=price, qty=1)


def test_s1_failure_blocks_regardless_of_everything_else() -> None:
    all_ok = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[], latency_ms=1.0
    )
    result = fuse_decision(
        _FAIL_S1,
        all_ok,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.1,
        cart_total_paise=100_000,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.BLOCK
    assert result.reason_code == "s1_revoked"


def test_any_violated_finding_blocks() -> None:
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED, "c1"), _finding(Verdict.VIOLATED, "c2")],
        unrequested_items=[],
        latency_ms=1.0,
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.1,
        cart_total_paise=100_000,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.BLOCK
    assert "c2" in result.reason_code


def test_undetermined_finding_steps_up_not_blocks() -> None:
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED, "c1"), _finding(Verdict.UNDETERMINED, "c2")],
        unrequested_items=[],
        latency_ms=1.0,
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.1,
        cart_total_paise=100_000,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.STEP_UP
    assert "c2" in result.reason_code


def test_small_unrequested_item_is_auto_stripped_and_allows() -> None:
    unrequested = _item("SP-BLK", 29_900)  # 7.9% of a 379,800-paise cart
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[unrequested], latency_ms=1.0
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.10,
        cart_total_paise=379_800,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.ALLOW
    assert result.stripped_skus == ["SP-BLK"]


def test_large_unrequested_item_steps_up_instead_of_stripping() -> None:
    unrequested = _item("EXPENSIVE", 200_000)  # over half the cart
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[unrequested], latency_ms=1.0
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.10,
        cart_total_paise=349_900,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.STEP_UP
    assert result.stripped_skus == []


def test_auto_strip_disabled_always_steps_up_on_unrequested_items() -> None:
    unrequested = _item("SP-BLK", 100)  # negligible value
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[unrequested], latency_ms=1.0
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=False,
        auto_strip_max_fraction=0.99,
        cart_total_paise=349_900,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.STEP_UP


def test_behaviour_anomaly_steps_up_when_constraints_otherwise_clear() -> None:
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[], latency_ms=1.0
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _ANOMALOUS_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.10,
        cart_total_paise=349_900,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.STEP_UP
    assert "burst_request_rate" in result.reason_code


def test_clean_cart_allows() -> None:
    s2 = FaithfulnessResult(
        findings=[_finding(Verdict.SATISFIED)], unrequested_items=[], latency_ms=1.0
    )
    result = fuse_decision(
        _PASS_S1,
        s2,
        _QUIET_S3,
        auto_strip_unrequested=True,
        auto_strip_max_fraction=0.10,
        cart_total_paise=349_900,
        behaviour_step_up_threshold=0.4,
    )
    assert result.outcome == DecisionOutcome.ALLOW
    assert result.reason_code == "all_constraints_satisfied"
