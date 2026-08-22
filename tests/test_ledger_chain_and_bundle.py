"""Phase 1 gate: hash-chain integrity — building a small chain of proof
bundles, and confirming that tampering with any single byte (in the payload,
`prev_hash`, `payload_hash`, or `signature`) breaks verification.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.ledger.bundle import build_proof_bundle, verify_proof_bundle
from apps.api.ledger.chain import GENESIS_HASH, verify_chain
from apps.api.ledger.crypto import generate_signing_key
from apps.api.models.schemas import (
    Adjudicator,
    Cart,
    CartItem,
    Constraint,
    ConstraintType,
    Decision,
    DecisionOutcome,
    Finding,
    Mandate,
    ProofBundlePayload,
    RazorpayIds,
    VelocityLimits,
    Verdict,
)


def _make_payload(*, price_paise: int = 349_900, decision_id: str = "dec-1") -> ProofBundlePayload:
    now = datetime.now(UTC)
    mandate = Mandate(
        id="mnd-1",
        principal_id="user-1",
        agent_id="agent-1",
        public_key="unused-in-this-test",
        signature="unused-in-this-test",
        budget_total_paise=400_000,
        budget_used_paise=0,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        intent_text="running shoes under ₹4000, size 9, not white",
        constraints=[
            Constraint(
                id="c1",
                type=ConstraintType.MAX_PRICE,
                field="price",
                operator="<=",
                value="400000",
                is_deterministic=True,
                source_span="under ₹4000",
            )
        ],
        issued_at=now,
        expires_at=now,
    )
    cart = Cart(
        id="cart-1",
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[
            CartItem(
                sku="NR-A9",
                name="Nova Runner",
                description="running shoe",
                unit_price_paise=price_paise,
                qty=1,
                attributes={"size": "UK9", "colour": "Ash"},
            )
        ],
        total_paise=price_paise,
    )
    decision = Decision(
        id=decision_id,
        cart_id=cart.id,
        outcome=DecisionOutcome.ALLOW,
        reason_code="all_constraints_satisfied",
        findings=[
            Finding(
                constraint_id="c1",
                verdict=Verdict.SATISFIED,
                evidence=f"{price_paise} <= 400000",
                confidence=1.0,
                adjudicator=Adjudicator.RULE,
            )
        ],
        behaviour_score=0.08,
        behaviour_signals=[],
        stripped_items=[],
        stage_latencies_ms={"s1_mandate": 4.0, "s2_faithfulness": 612.0},
        razorpay_order_id="order_test",
        razorpay_payment_id="pay_test",
    )
    return ProofBundlePayload(
        mandate_snapshot=mandate,
        intent=mandate.intent_text,
        cart=cart,
        findings=decision.findings,
        behaviour_score=decision.behaviour_score,
        behaviour_signals=decision.behaviour_signals,
        decision=decision,
        razorpay_ids=RazorpayIds(order_id="order_test", payment_id="pay_test", captured_at=now),
    )


def test_single_bundle_verifies() -> None:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id,
        prev_hash=GENESIS_HASH,
        payload=payload,
        signing_key=key,
    )
    assert verify_proof_bundle(bundle, key.public_key()) is True


def test_chain_of_three_bundles_verifies() -> None:
    key = generate_signing_key()
    prev_hash = GENESIS_HASH
    bundles = []
    for i in range(3):
        payload = _make_payload(price_paise=300_000 + i)
        bundle = build_proof_bundle(
            decision_id=payload.decision.id, prev_hash=prev_hash, payload=payload, signing_key=key
        )
        bundles.append(bundle)
        prev_hash = bundle.payload_hash

    for bundle in bundles:
        assert verify_proof_bundle(bundle, key.public_key()) is True

    entries = [(b.prev_hash, b.payload.model_dump(mode="json"), b.payload_hash) for b in bundles]
    assert verify_chain(entries) is True


@pytest.mark.parametrize("field", ["intent", "cart", "decision"])
def test_tampering_with_payload_field_breaks_verification(field: str) -> None:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )

    dump = bundle.model_dump(mode="json")
    if field == "intent":
        dump["payload"]["intent"] = dump["payload"]["intent"] + " TAMPERED"
    elif field == "cart":
        dump["payload"]["cart"]["total_paise"] += 1
    elif field == "decision":
        dump["payload"]["decision"]["outcome"] = "BLOCK"

    tampered_bundle = type(bundle).model_validate(dump)
    assert verify_proof_bundle(tampered_bundle, key.public_key()) is False


def test_tampering_with_prev_hash_breaks_verification() -> None:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )

    dump = bundle.model_dump(mode="json")
    dump["prev_hash"] = "1" * 64
    tampered_bundle = type(bundle).model_validate(dump)
    assert verify_proof_bundle(tampered_bundle, key.public_key()) is False


def test_tampering_with_payload_hash_breaks_verification() -> None:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )

    dump = bundle.model_dump(mode="json")
    flipped = list(dump["payload_hash"])
    flipped[0] = "0" if flipped[0] != "0" else "1"
    dump["payload_hash"] = "".join(flipped)
    tampered_bundle = type(bundle).model_validate(dump)
    assert verify_proof_bundle(tampered_bundle, key.public_key()) is False


def test_tampering_with_signature_breaks_verification() -> None:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )

    dump = bundle.model_dump(mode="json")
    dump["signature"] = "AAAA" + dump["signature"][4:]
    tampered_bundle = type(bundle).model_validate(dump)
    assert verify_proof_bundle(tampered_bundle, key.public_key()) is False


def test_splicing_a_different_predecessor_breaks_the_chain() -> None:
    """Even if an attacker re-signs a bundle after swapping its predecessor,
    the *next* bundle in the real chain still points at the original
    `prev_hash` and will no longer match — the chain, not just one entry,
    is what breaks."""
    key = generate_signing_key()
    payload_a = _make_payload(price_paise=100_000)
    bundle_a = build_proof_bundle(
        decision_id=payload_a.decision.id,
        prev_hash=GENESIS_HASH,
        payload=payload_a,
        signing_key=key,
    )
    payload_b = _make_payload(price_paise=200_000)
    bundle_b = build_proof_bundle(
        decision_id=payload_b.decision.id,
        prev_hash=bundle_a.payload_hash,
        payload=payload_b,
        signing_key=key,
    )

    forged_prev_hash = "f" * 64
    entries = [
        (bundle_a.prev_hash, bundle_a.payload.model_dump(mode="json"), bundle_a.payload_hash),
        (forged_prev_hash, bundle_b.payload.model_dump(mode="json"), bundle_b.payload_hash),
    ]
    assert verify_chain(entries) is False
