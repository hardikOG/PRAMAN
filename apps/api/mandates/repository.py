"""Persistence for mandates — converts between the domain `Mandate` model
and its `MandateRow`/`ConstraintRow` ORM rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.schemas import Constraint, ConstraintType, Mandate, VelocityLimits
from apps.api.models.tables import ConstraintRow, MandateRow


def _to_row(mandate: Mandate) -> MandateRow:
    return MandateRow(
        id=mandate.id,
        principal_id=mandate.principal_id,
        agent_id=mandate.agent_id,
        public_key=mandate.public_key,
        signature=mandate.signature,
        budget_total_paise=mandate.budget_total_paise,
        budget_used_paise=mandate.budget_used_paise,
        per_txn_cap_paise=mandate.per_txn_cap_paise,
        merchant_allowlist=list(mandate.merchant_allowlist),
        category_allowlist=list(mandate.category_allowlist),
        velocity_max_txn_per_hour=mandate.velocity.max_txn_per_hour,
        velocity_max_txn_per_day=mandate.velocity.max_txn_per_day,
        auto_strip_unrequested=mandate.auto_strip_unrequested,
        intent_text=mandate.intent_text,
        issued_at=mandate.issued_at,
        expires_at=mandate.expires_at,
        revoked_at=mandate.revoked_at,
        constraints=[
            ConstraintRow(
                id=c.id,
                type=c.type.value,
                field=c.field,
                operator=c.operator,
                value=c.value,
                is_deterministic=c.is_deterministic,
                source_span=c.source_span,
            )
            for c in mandate.constraints
        ],
    )


def _to_domain(row: MandateRow) -> Mandate:
    return Mandate(
        id=row.id,
        principal_id=row.principal_id,
        agent_id=row.agent_id,
        public_key=row.public_key,
        signature=row.signature,
        budget_total_paise=row.budget_total_paise,
        budget_used_paise=row.budget_used_paise,
        per_txn_cap_paise=row.per_txn_cap_paise,
        merchant_allowlist=list(row.merchant_allowlist),
        category_allowlist=list(row.category_allowlist),
        velocity=VelocityLimits(
            max_txn_per_hour=row.velocity_max_txn_per_hour,
            max_txn_per_day=row.velocity_max_txn_per_day,
        ),
        auto_strip_unrequested=row.auto_strip_unrequested,
        intent_text=row.intent_text,
        constraints=[
            Constraint(
                id=c.id,
                type=ConstraintType(c.type),
                field=c.field,
                operator=c.operator,
                value=c.value,
                is_deterministic=c.is_deterministic,
                source_span=c.source_span,
            )
            for c in row.constraints
        ],
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


async def save_mandate(session: AsyncSession, mandate: Mandate) -> None:
    """Persist a newly issued mandate. Complexity: O(k) in constraint count."""
    session.add(_to_row(mandate))
    await session.flush()


async def get_mandate(session: AsyncSession, mandate_id: str) -> Mandate | None:
    """Fetch a mandate by id, or `None` if it doesn't exist."""
    result = await session.execute(
        select(MandateRow)
        .where(MandateRow.id == mandate_id)
        .options(selectinload(MandateRow.constraints))
    )
    row = result.scalar_one_or_none()
    return _to_domain(row) if row is not None else None


async def revoke_mandate(
    session: AsyncSession, mandate_id: str, revoked_at: datetime
) -> Mandate | None:
    """Mark a mandate revoked, returning the updated domain object, or
    `None` if no such mandate exists.

    Idempotent: revoking an already-revoked mandate just returns it as-is
    rather than overwriting the original `revoked_at`.
    """
    result = await session.execute(
        select(MandateRow)
        .where(MandateRow.id == mandate_id)
        .options(selectinload(MandateRow.constraints))
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = revoked_at
        await session.flush()
    return _to_domain(row)


def new_id() -> str:
    """Generate a fresh id for a mandate or constraint."""
    return str(uuid.uuid4())
