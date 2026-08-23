"""The console's Ledger feed and proof inspector: read-only endpoints over
persisted decisions, carts, and proof bundles.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.db import get_db_session
from apps.api.gateway import confirm_step_up
from apps.api.gateway.repository import get_decision, list_recent_decisions
from apps.api.ledger.crypto import load_or_create_signing_key
from apps.api.ledger.repository import get_proof_bundle_by_decision
from apps.api.models.tables import CartRow, DecisionRow
from apps.api.payments import get_payment_executor
from apps.api.redis_client import get_redis

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _serialize_cart(cart: CartRow | None) -> dict | None:
    if cart is None:
        return None
    return {
        "id": cart.id,
        "merchant_id": cart.merchant_id,
        "total_paise": cart.total_paise,
        "currency": cart.currency,
        "items": [
            {
                "sku": item.sku,
                "name": item.name,
                "unit_price_paise": item.unit_price_paise,
                "qty": item.qty,
                "attributes": item.attributes,
            }
            for item in cart.items
        ],
    }


def _serialize_decision(decision: DecisionRow) -> dict:
    return {
        "id": decision.id,
        "cart_id": decision.cart_id,
        "outcome": decision.outcome,
        "reason_code": decision.reason_code,
        "behaviour_score": decision.behaviour_score,
        "behaviour_signals": decision.behaviour_signals,
        "stripped_items": decision.stripped_items,
        "stage_latencies_ms": decision.stage_latencies_ms,
        "razorpay_order_id": decision.razorpay_order_id,
        "razorpay_payment_id": decision.razorpay_payment_id,
        "created_at": decision.created_at.isoformat(),
        "cart": _serialize_cart(decision.cart),
        "findings": [
            {
                "constraint_id": f.constraint_id,
                "verdict": f.verdict,
                "evidence": f.evidence,
                "confidence": f.confidence,
                "adjudicator": f.adjudicator,
            }
            for f in decision.findings
        ],
    }


@router.get("")
async def list_decisions(
    limit: int = 50, session: AsyncSession = Depends(get_db_session)
) -> list[dict]:
    """The Ledger feed: most recent decisions first."""
    rows = await list_recent_decisions(session, limit=limit)
    return [_serialize_decision(row) for row in rows]


@router.get("/{decision_id}")
async def get_decision_detail(
    decision_id: str, session: AsyncSession = Depends(get_db_session)
) -> dict:
    """One decision's full detail — what the console's proof inspector
    opens into."""
    row = await get_decision(session, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return _serialize_decision(row)


@router.get("/{decision_id}/proof")
async def get_decision_proof(
    decision_id: str, session: AsyncSession = Depends(get_db_session)
) -> dict:
    """The signed proof bundle for a decision, if it reached ALLOW."""
    bundle = await get_proof_bundle_by_decision(session, decision_id)
    if bundle is None:
        raise HTTPException(
            status_code=404, detail="no proof bundle for this decision (it did not ALLOW)"
        )
    return bundle.model_dump(mode="json")


class StepUpConfirmRequest(BaseModel):
    token: str


@router.post("/step-up/confirm")
async def confirm_step_up_route(
    body: StepUpConfirmRequest, session: AsyncSession = Depends(get_db_session)
) -> dict:
    """The human's one-tap confirm: redeem a STEP_UP token, capture payment,
    and emit a new ALLOW decision + proof bundle — see
    `gateway.pipeline.confirm_step_up` for exactly what this does and does
    not mutate. Redemption is single-use (Redis `GETDEL`); a token that's
    already been used, expired, or never existed returns 409, not a silent
    no-op, since the console needs to tell "already confirmed" apart from
    "still pending" and "capture succeeded just now."
    """
    settings = get_settings()
    result = await confirm_step_up(
        session=session,
        redis=get_redis(),
        token=body.token,
        ledger_signing_key=load_or_create_signing_key(settings.ledger_signing_key_path),
        payment_executor=get_payment_executor(),
    )
    if not result.ok:
        raise HTTPException(status_code=409, detail=result.reason)
    assert result.decision is not None and result.proof_bundle is not None
    return {
        "decision": result.decision.model_dump(mode="json"),
        "proof_bundle": result.proof_bundle.model_dump(mode="json"),
    }
