"""Persistence for carts and decisions — what the console (Phase 7) reads
back for the live ledger feed and the proof inspector.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.schemas import Adjudicator, Cart, CartItem, Decision, Finding, Verdict
from apps.api.models.tables import CartItemRow, CartRow, DecisionRow, FindingRow


async def save_cart(session: AsyncSession, cart: Cart) -> None:
    """Persist a cart and its line items. Complexity: O(k) in item count."""
    session.add(
        CartRow(
            id=cart.id,
            mandate_id=cart.mandate_id,
            merchant_id=cart.merchant_id,
            quote_id=cart.quote_id,
            total_paise=cart.total_paise,
            currency=cart.currency,
            items=[
                CartItemRow(
                    id=str(uuid.uuid4()),
                    sku=item.sku,
                    name=item.name,
                    description=item.description,
                    unit_price_paise=item.unit_price_paise,
                    qty=item.qty,
                    attributes=item.attributes,
                )
                for item in cart.items
            ],
        )
    )
    await session.flush()


async def save_decision(session: AsyncSession, decision: Decision) -> None:
    """Persist a decision and its per-constraint findings.

    Complexity: O(k) in finding count.
    """
    session.add(
        DecisionRow(
            id=decision.id,
            cart_id=decision.cart_id,
            outcome=decision.outcome.value,
            reason_code=decision.reason_code,
            behaviour_score=decision.behaviour_score,
            behaviour_signals=decision.behaviour_signals,
            stripped_items=decision.stripped_items,
            stage_latencies_ms=decision.stage_latencies_ms,
            razorpay_order_id=decision.razorpay_order_id,
            razorpay_payment_id=decision.razorpay_payment_id,
            findings=[
                FindingRow(
                    id=str(uuid.uuid4()),
                    constraint_id=f.constraint_id,
                    verdict=f.verdict.value,
                    evidence=f.evidence,
                    confidence=f.confidence,
                    adjudicator=f.adjudicator.value,
                )
                for f in decision.findings
            ],
        )
    )
    await session.flush()


async def list_recent_decisions(session: AsyncSession, *, limit: int = 50) -> list[DecisionRow]:
    """The console's Ledger feed: most recent decisions first, with their
    cart (and its items) and findings eager-loaded in the same round trip.

    Complexity: O(limit) rows plus their related rows.
    """
    result = await session.execute(
        select(DecisionRow)
        .options(
            selectinload(DecisionRow.findings),
            selectinload(DecisionRow.cart).selectinload(CartRow.items),
        )
        .order_by(DecisionRow.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_decision(session: AsyncSession, decision_id: str) -> DecisionRow | None:
    """Fetch one decision by id, with cart/items/findings/proof_bundle
    eager-loaded — what the console's proof inspector and decision-detail
    views need, and what `pipeline.confirm_step_up` needs to rebuild the
    originally-flagged cart without a lazy-load outside an async context."""
    result = await session.execute(
        select(DecisionRow)
        .where(DecisionRow.id == decision_id)
        .options(
            selectinload(DecisionRow.findings),
            selectinload(DecisionRow.cart).selectinload(CartRow.items),
            selectinload(DecisionRow.proof_bundle),
        )
    )
    return result.scalar_one_or_none()


def cart_from_row(row: CartRow) -> Cart:
    """Reconstruct the domain `Cart` a persisted `CartRow` (with `.items`
    eager-loaded — see `get_decision`) represents.

    Used by step-up confirmation (`pipeline.confirm_step_up`), which has to
    rebuild the originally-flagged cart to capture payment against it — the
    only other places a `Cart` gets built are fresh, from a live quote, not
    read back from storage.
    """
    return Cart(
        id=row.id,
        mandate_id=row.mandate_id,
        merchant_id=row.merchant_id,
        quote_id=row.quote_id,
        items=[
            CartItem(
                sku=item.sku,
                name=item.name,
                description=item.description,
                unit_price_paise=item.unit_price_paise,
                qty=item.qty,
                attributes=item.attributes,
            )
            for item in row.items
        ],
        total_paise=row.total_paise,
        currency=row.currency,
    )


def findings_from_rows(rows: list[FindingRow]) -> list[Finding]:
    """Reconstruct domain `Finding`s from persisted `FindingRow`s — the
    STEP_UP decision's own findings, carried forward unchanged into the new
    ALLOW decision `confirm_step_up` creates on confirmation."""
    return [
        Finding(
            constraint_id=row.constraint_id,
            verdict=Verdict(row.verdict),
            evidence=row.evidence,
            confidence=row.confidence,
            adjudicator=Adjudicator(row.adjudicator),
        )
        for row in rows
    ]
