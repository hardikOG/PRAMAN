"""Orchestrates S1 → S2 → S3 → S4 for one authorization attempt, then (on
ALLOW) captures payment and emits a signed proof bundle.

This is the one place that calls all four stages in order and persists
their combined output — everything upstream (mandate service, storefront,
individual stages) stays independently testable; this module is what wires
them into "one call, one decision, one commit."
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.gateway.behaviour_events import cart_signature, record_agent_event
from apps.api.gateway.policy import fuse_decision
from apps.api.gateway.repository import save_cart, save_decision
from apps.api.gateway.stage_behaviour import BehaviourResult, evaluate_behaviour
from apps.api.gateway.stage_faithfulness import FaithfulnessResult, evaluate_faithfulness
from apps.api.gateway.stage_mandate import evaluate_mandate
from apps.api.gateway.step_up import issue_step_up_token
from apps.api.ledger.bundle import build_proof_bundle
from apps.api.ledger.repository import get_latest_payload_hash, save_proof_bundle
from apps.api.llm_client import LLMClient
from apps.api.mandates.velocity import record_transaction
from apps.api.models.schemas import (
    Cart,
    CartItem,
    Decision,
    DecisionOutcome,
    Mandate,
    ProofBundle,
    ProofBundlePayload,
    RazorpayIds,
)
from apps.api.payments.executor import PaymentExecutor


class QuoteItemLike(Protocol):
    """The subset of a storefront `QuoteLineItem` that `quote_to_cart`
    needs — a `Protocol`, not an import of the concrete class, so the
    gateway doesn't take a reverse dependency on `mcp_storefront`.

    Declared as read-only properties, not plain attributes: `QuoteLineItem`
    is a frozen Pydantic model, and a Protocol with settable-attribute
    annotations doesn't structurally match a read-only one.
    """

    @property
    def sku(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def category(self) -> str: ...
    @property
    def unit_price_paise(self) -> int: ...
    @property
    def qty(self) -> int: ...
    @property
    def attributes(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class PipelineThresholds:
    """Every tunable the pipeline's stages need, gathered in one place so
    callers (the API route, the eval harness, tests) build it once from
    `Settings` rather than threading a dozen scalars through."""

    replay_guard_ttl_seconds: int
    faithfulness_min_confidence: float
    behaviour_max_req_per_sec: float
    behaviour_burst_window_seconds: float
    behaviour_probe_window_seconds: float
    behaviour_probe_min_quotes: int
    behaviour_loop_min_repeats: int
    auto_strip_max_fraction: float
    behaviour_step_up_threshold: float
    step_up_ttl_seconds: int
    behaviour_event_stream_maxlen: int


@dataclass(frozen=True)
class AuthorizationResult:
    """What one `authorize()` call produces: the decision, a proof bundle
    (only on ALLOW), and a step-up token (only on STEP_UP)."""

    decision: Decision
    proof_bundle: ProofBundle | None
    step_up_token: str | None


def quote_to_cart(
    *,
    cart_id: str,
    mandate_id: str,
    merchant_id: str,
    quote_id: str,
    items: Sequence[QuoteItemLike],
    currency: str,
) -> Cart:
    """Convert a storefront `Quote`'s line items into a gateway `Cart`.

    The quote's `category` (not part of the fixed `CartItem` schema) is
    folded into `attributes["category"]`, which is exactly where S2's
    CATEGORY-constraint rule check and target-item identification look for
    it (see stage_faithfulness.py).
    """
    cart_items = [
        CartItem(
            sku=item.sku,
            name=item.name,
            description="",
            unit_price_paise=item.unit_price_paise,
            qty=item.qty,
            attributes={**item.attributes, "category": item.category},
        )
        for item in items
    ]
    return Cart(
        id=cart_id,
        mandate_id=mandate_id,
        merchant_id=merchant_id,
        quote_id=quote_id,
        items=cart_items,
        total_paise=sum(i.line_total_paise for i in cart_items),
        currency=currency,
    )


async def authorize(
    *,
    session: AsyncSession,
    redis: Redis,
    mandate: Mandate,
    cart: Cart,
    llm_client: LLMClient,
    ledger_signing_key: Ed25519PrivateKey,
    payment_executor: PaymentExecutor,
    thresholds: PipelineThresholds,
    at: datetime | None = None,
    include_s2: bool = True,
    include_s3: bool = True,
) -> AuthorizationResult:
    """Run the full S1-S4 pipeline for one cart, persisting cart, decision,
    and (on ALLOW) a signed proof bundle.

    `include_s2`/`include_s3` exist for the eval harness's ablation study
    (Phase 8) — set False to measure what S1 alone (or S1+S3, or S1+S2)
    would have decided, with the skipped stage treated as trivially passing
    rather than removed from the pipeline's shape.

    Complexity: O(1) S1 checks + one LLM call per LLM-adjudicated constraint
    (S2) + O(1) S3 checks, plus one payment-executor round trip on ALLOW.
    Failure cases: propagates whatever the payment executor raises on
        capture failure — an ALLOW decision whose payment fails is a bug to
        surface loudly, not swallow into a false proof bundle.
    """
    at = at or datetime.now(UTC)

    s1 = await evaluate_mandate(
        redis, mandate, cart, at, replay_guard_ttl_seconds=thresholds.replay_guard_ttl_seconds
    )

    if s1.passed:
        cart_sig = cart_signature([(i.sku, i.qty) for i in cart.items])
        s2 = (
            evaluate_faithfulness(
                cart,
                mandate.constraints,
                llm_client,
                min_confidence=thresholds.faithfulness_min_confidence,
            )
            if include_s2
            else FaithfulnessResult(findings=[], unrequested_items=[], latency_ms=0.0)
        )
        # Read before write: this attempt's own event must not count toward
        # its own burst/probe/loop score, only prior attempts should. This
        # always runs (even with include_s3=False) so the event stream
        # stays real for whichever ablation configuration runs next —
        # only whether the *score* feeds the decision is toggled below.
        s3_measured = await evaluate_behaviour(
            redis,
            mandate.agent_id,
            at,
            cart_signature=cart_sig,
            max_req_per_sec=thresholds.behaviour_max_req_per_sec,
            burst_window_seconds=thresholds.behaviour_burst_window_seconds,
            probe_window_seconds=thresholds.behaviour_probe_window_seconds,
            probe_min_quotes=thresholds.behaviour_probe_min_quotes,
            loop_min_repeats=thresholds.behaviour_loop_min_repeats,
        )
        s3 = (
            s3_measured
            if include_s3
            else BehaviourResult(score=0.0, signals=[], latency_ms=s3_measured.latency_ms)
        )
        await record_transaction(redis, mandate.id, at)
        await record_agent_event(
            redis,
            mandate.agent_id,
            "cart_submitted",
            at,
            cart_signature=cart_sig,
            maxlen=thresholds.behaviour_event_stream_maxlen,
        )
    else:
        s2 = FaithfulnessResult(findings=[], unrequested_items=[], latency_ms=0.0)
        s3 = BehaviourResult(score=0.0, signals=[], latency_ms=0.0)

    policy = fuse_decision(
        s1,
        s2,
        s3,
        auto_strip_unrequested=mandate.auto_strip_unrequested,
        auto_strip_max_fraction=thresholds.auto_strip_max_fraction,
        cart_total_paise=cart.total_paise,
        behaviour_step_up_threshold=thresholds.behaviour_step_up_threshold,
    )

    decision = Decision(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        outcome=policy.outcome,
        reason_code=policy.reason_code,
        findings=s2.findings,
        behaviour_score=s3.score,
        behaviour_signals=s3.signals,
        stripped_items=policy.stripped_skus,
        stage_latencies_ms={"s1": s1.latency_ms, "s2": s2.latency_ms, "s3": s3.latency_ms},
    )

    proof_bundle: ProofBundle | None = None
    step_up_token: str | None = None

    if policy.outcome == DecisionOutcome.ALLOW:
        stripped_value = sum(
            i.line_total_paise for i in cart.items if i.sku in policy.stripped_skus
        )
        payable_amount = cart.total_paise - stripped_value

        order = await payment_executor.create_order(
            amount_paise=payable_amount, currency=cart.currency, receipt=cart.id
        )
        payment = await payment_executor.capture_payment(
            order_id=order.order_id, amount_paise=payable_amount
        )
        decision = decision.model_copy(
            update={"razorpay_order_id": order.order_id, "razorpay_payment_id": payment.payment_id}
        )

        prev_hash = await get_latest_payload_hash(session)
        payload = ProofBundlePayload(
            mandate_snapshot=mandate,
            intent=mandate.intent_text,
            cart=cart,
            findings=s2.findings,
            behaviour_score=s3.score,
            behaviour_signals=s3.signals,
            decision=decision,
            razorpay_ids=RazorpayIds(
                order_id=order.order_id,
                payment_id=payment.payment_id,
                captured_at=payment.captured_at,
            ),
        )
        proof_bundle = build_proof_bundle(
            decision_id=decision.id,
            prev_hash=prev_hash,
            payload=payload,
            signing_key=ledger_signing_key,
        )
        await save_proof_bundle(session, proof_bundle)

    elif policy.outcome == DecisionOutcome.STEP_UP:
        step_up_token = await issue_step_up_token(
            redis, decision.id, ttl_seconds=thresholds.step_up_ttl_seconds
        )

    # A replay is provably a resubmission of a cart id already persisted by
    # the original attempt — re-inserting it would violate the cart table's
    # primary key. Only the decision (a fresh row per attempt) is recorded,
    # so a replay attempt still shows up in the ledger, just without trying
    # to duplicate the cart it's replaying.
    if s1.reason_code != "replay_detected":
        await save_cart(session, cart)
    await save_decision(session, decision)

    return AuthorizationResult(
        decision=decision, proof_bundle=proof_bundle, step_up_token=step_up_token
    )
